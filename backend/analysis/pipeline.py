"""Full-document orchestration; coverage is independent from detector probabilities."""

from collections import Counter
from dataclasses import asdict
import hashlib
from pathlib import Path
import time

from backend.analysis.aggregation import aggregate
from backend.analysis.chunking import make_chunks
from backend.analysis.extraction import extract_pdf, validate_pdf
from backend.analysis.segmentation import english_gate, segment_document
from backend.analysis.types import AnalysisError
from backend.analysis.source import source_document
from backend.config import DISCLAIMER, Settings
from backend.detectors.artifacts import MODEL_INFO


class AnalysisPipeline:
    def __init__(self, settings: Settings, runtime, extractor=extract_pdf):
        self.settings, self.runtime, self.extractor = settings, runtime, extractor

    def run(self, path: Path, threshold: float, progress=lambda *args: None, cancelled=lambda: False) -> dict:
        started = time.monotonic()
        timings = {}

        def check():
            if cancelled():
                raise AnalysisError("shutdown", "Analysis stopped because the backend is shutting down.")
            if time.monotonic()-started > self.settings.job_timeout_seconds:
                raise AnalysisError("analysis_timeout", "Analysis exceeded its time budget; no partial result was published.")

        progress("validating", 0, 1)
        size = path.stat().st_size
        if size > self.settings.max_upload_bytes:
            raise AnalysisError("upload_limit", "PDF exceeds the upload limit.")
        data = path.read_bytes()
        file_format = {'pdf':'pdf', 'py':'python', 'js':'javascript', 'txt':'text'}.get(path.suffix.lstrip('.'), 'pdf')
        if file_format == 'pdf':
            validate_pdf(data, self.settings)
        else:
            document = source_document(data, file_format, self.settings)
        digest = hashlib.sha256(data).hexdigest()
        del data
        progress("extracting", 0, 1)
        if file_format == 'pdf':
            document = self.extractor(path, self.settings, progress, check)
        timings["extraction_and_ocr_seconds"] = time.monotonic()-started
        check()
        progress("segmenting", 0, 1)
        segments = segment_document(document)
        timings["segmentation_seconds"] = time.monotonic()-started-timings["extraction_and_ocr_seconds"]
        summaries = {}
        analysis_sources = []
        for kind in ("text", "code"):
            check()
            progress("scoring_"+kind, 0, 1)
            mode_started = time.monotonic()
            recognized_chars = sum(len(segment.text) for segment in segments if segment.kind == kind)
            summary = {
                **MODEL_INFO[kind], "threshold": threshold,
                "status": "no_content" if not recognized_chars else "model_unavailable",
                "recognized_characters": recognized_chars, "analyzed_characters": 0,
                "candidate_tokens": None, "candidate_chunks": None,
                "skipped_tokens_by_reason": {}, "chunk_scores": [], **aggregate([], threshold),
                "unscored_passages": [],
                "metric_label": "Share of analyzed content flagged",
                "validation_label": "Unvalidated for university submissions",
                "metric_note": "Flagged-content share is a detector signal, not the fraction actually authored by AI.",
            }
            if not recognized_chars:
                summaries[kind] = summary
                continue
            try:
                detector = self.runtime.get_detector(kind)
            except RuntimeError:
                summary['unscored_passages'] = [{**asdict(segment), 'reason': 'model_unavailable'}
                                               for segment in segments if segment.kind == kind]
                summaries[kind] = summary
                continue
            try:
                chunks = make_chunks(segments, detector.tokenizer, kind, detector.max_tokens, self.settings.max_chunks,
                                     getattr(self.settings, f'min_{kind}_chunk_tokens'))
            except AnalysisError:
                raise
            except Exception:
                summary["status"] = "inference_failed"
                summary["error"] = "Tokenizer failed; no scores were published for this modality."
                summary['unscored_passages'] = [{**asdict(segment), 'reason': 'tokenizer_failed'}
                                               for segment in segments if segment.kind == kind]
                summaries[kind] = summary
                continue
            minimum = getattr(self.settings, f"min_{kind}_chunk_tokens")
            total_minimum = getattr(self.settings, f"min_{kind}_total_tokens")
            summary["candidate_tokens"] = sum(chunk.content_tokens for chunk in chunks)
            summary["candidate_chunks"] = len(chunks)
            eligible, skipped = [], Counter()
            for chunk in chunks:
                reason = chunk.reason or ("short_chunk" if chunk.content_tokens < minimum else "")
                if not reason and kind == "text" and english_gate(chunk.text) != "english_likely":
                    reason = "non_english_or_unknown"
                if reason:
                    skipped[reason] += chunk.content_tokens
                    summary['unscored_passages'].append({**asdict(chunk), 'reason': reason})
                else:
                    eligible.append(chunk)
            if sum(chunk.content_tokens for chunk in eligible) < total_minimum:
                skipped["insufficient_total_content"] += sum(chunk.content_tokens for chunk in eligible)
                summary['unscored_passages'].extend({**asdict(chunk), 'reason': 'insufficient_total_content'} for chunk in eligible)
                eligible = []
            summary["minimum_content_policy"] = {"chunk_tokens":minimum,"total_tokens":total_minimum,
                                                "note":"Practical conservative guards, not validated reliability thresholds."}
            summary["skipped_tokens_by_reason"] = dict(skipped)
            if not eligible:
                summary["status"] = "insufficient_or_unsupported_content"
                summaries[kind] = summary
                continue
            scored = []
            try:
                for start in range(0, len(eligible), detector.batch_size):
                    check()
                    batch = eligible[start:start+detector.batch_size]
                    probabilities = detector.predict_chunks([chunk.text for chunk in batch])
                    if len(probabilities) != len(batch):
                        raise RuntimeError("Detector returned the wrong number of chunk scores")
                    for chunk, score in zip(batch, probabilities):
                        if score.input_tokens != chunk.input_tokens:
                            raise RuntimeError("Tokenizer count changed between chunking and scoring")
                        scored.append({**asdict(chunk), "probability":score.probability,
                                        "pages":sorted({source["page"] for source in chunk.sources if 'page' in source})})
                    progress("scoring_"+kind, min(start+detector.batch_size,len(eligible)), len(eligible))
                metrics = aggregate(scored, threshold)
            except AnalysisError:
                raise
            except Exception:
                summary["status"] = "inference_failed"
                summary["error"] = "Inference failed; no partial scores were published for this modality."
                summary["skipped_tokens_by_reason"]["inference_failed"] = sum(chunk.content_tokens for chunk in eligible)
                summary['unscored_passages'].extend({**asdict(chunk), 'reason': 'inference_failed'} for chunk in eligible)
            else:
                summary.update(metrics)
                summary["status"] = "scored"
                summary["analyzed_characters"] = sum(len(item["text"]) for item in scored)
                summary["chunk_scores"] = scored
                analysis_sources.extend(source for item in scored for source in item["sources"])
            timings[kind+"_inference_seconds"] = time.monotonic()-mode_started
            summaries[kind] = summary
        check()
        progress("aggregating", 0, 1)
        region_counts = Counter(region["status"] for page in document.pages for region in page.regions)
        unread = {"ocr_unavailable", "ocr_region_limit", "ocr_failed", "needs_ocr", "unclassified_image"}
        pages_with_scores = {source["page"] for source in analysis_sources if 'page' in source}
        exclusions = Counter()
        for segment in segments:
            if segment.kind in {"excluded", "uncertain"}:
                exclusions[segment.reason] += len(segment.text)
        warnings = list(document.warnings) + ["Language and segmentation decisions are heuristic; review flagged passages in context."]
        if any(region_counts[status] for status in unread):
            warnings.append("Some image regions were unread: detector summaries do not represent the entire visual document.")
        timings["total_seconds"] = time.monotonic()-started
        return {
            "schema_version":"2.0", "document":{"sha256":digest,"bytes":size,
                "format":file_format,"pages":len(document.pages) if file_format=='pdf' else None,"engine":document.engine},
            "text":summaries["text"],"code":summaries["code"],"timings":timings,"warnings":warnings,"disclaimer":DISCLAIMER,
            "coverage":{
                "pages_processed":len(document.pages), "pages_with_scored_content":sorted(pages_with_scores),
                "native_characters":sum(len(line.text) for page in document.pages for line in page.lines if line.method=="native"),
                "source_characters":len(document.source_text) if document.source_text is not None else 0,
                "duplicate_regions_removed":sum(page.duplicate_regions_removed for page in document.pages),
                "recognized_characters":sum(len(segment.text) for segment in segments),
                "analyzed_characters":sum(item['analyzed_characters'] for item in summaries.values()),
                "unscored_characters":sum(sum(len(passage['text']) for passage in item['unscored_passages']) for item in summaries.values()),
                "ocr_characters":sum(len(line.text) for page in document.pages for line in page.lines if line.method=="ocr"),
                "image_regions_by_status":dict(region_counts),
                "unread_image_regions":sum(region_counts[status] for status in unread),
                "excluded_characters_by_reason":dict(exclusions),
                "note":"No percentage of unseen visual content is estimated. Token counts exclude special tokens and padding.",
                "pages":[{"number":page.number,"width":page.width,"height":page.height,"status":page.status,
                          "native_lines":sum(line.method=="native" for line in page.lines),
                          "ocr_lines":sum(line.method=="ocr" for line in page.lines),
                          "regions":page.regions,"warnings":page.warnings} for page in document.pages],
            },
            "exclusions":[{"id":segment.id,"kind":segment.kind,"reason":segment.reason,"text":segment.text,
                           "characters":len(segment.text),"sources":segment.sources}
                          for segment in segments if segment.kind in {"excluded","uncertain"}],
        }
