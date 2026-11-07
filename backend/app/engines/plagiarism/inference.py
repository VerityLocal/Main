"""Candidate retrieval, original-span alignment and optional STS verification."""

from collections import defaultdict

from backend.app.document.chunking import passage_spans
from backend.app.engines.hallucination.bm25_retrieval import BM25
from backend.app.engines.plagiarism.alignment import align
from backend.app.engines.plagiarism.dense_retrieval import DenseRetriever
from backend.app.engines.plagiarism.minhash import MinHashLSH
from backend.app.engines.plagiarism.verification import pair_score
from backend.app.engines.plagiarism.winnowing import rolling_hashes, tokens, winnow


def analyze(document, sources, models, config, context):
    passages = [(source, span) for source in sources for span in passage_spans(source.text)]
    user_passages = passage_spans(document.extracted_text)
    lsh = MinHashLSH(**config.retrieval.minhash.model_dump())
    for source in sources:
        context.check()
        lsh.add(source.source_id, source.text)
    minhash_candidates = lsh.query(document.extracted_text)
    fingerprint_index = defaultdict(set)
    k = config.retrieval.winnowing.k_gram_size
    window = config.retrieval.winnowing.window_size
    for i, (_, span) in enumerate(passages):
        context.check()
        for value, _ in winnow(rolling_hashes(tokens(span.text), k), window):
            fingerprint_index[value].add(i)
    bm25 = BM25([span.text for _, span in passages])
    findings, seen = [], set()
    dense = DenseRetriever(models, context.check)
    for user_span in user_passages[:32]:
        context.check()
        candidates = {i for i, _ in bm25.search(user_span.text, k=4)}
        for value, _ in winnow(rolling_hashes(tokens(user_span.text), k), window):
            candidates.update(fingerprint_index.get(value, ()))
        candidates = sorted(
            candidates, key=lambda i: (passages[i][0].source_id not in minhash_candidates, i)
        )[:12]
        for i in candidates:
            source, source_span = passages[i]
            for match in align(user_span.text, source_span.text, min_words=k):
                start, end = (
                    user_span.start_offset + match["start_offset"],
                    user_span.start_offset + match["end_offset"],
                )
                source_start = source_span.start_offset + match["source_start_offset"]
                source_end = source_span.start_offset + match["source_end_offset"]
                key = (source.source_id, start, end, source_start, source_end)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    {
                        "finding_id": f"match_{len(findings)}",
                        "document_id": document.document_id,
                        "revision": document.revision,
                        "offset_unit": "utf16_code_unit",
                        "start_offset": start,
                        "end_offset": end,
                        "source_id": source.source_id,
                        "source_title": source.title,
                        "source_url": source.url,
                        "source_start_offset": source_start,
                        "source_end_offset": source_end,
                        "category": match["category"],
                        "similarity_score": 1.0,
                        "verification_score": None,
                        "retrieval_method": "winnowing_bm25_minhash_candidates",
                        "confidence": None,
                        "diagnostics": {
                            "equality": "normalized_lexical_tokens",
                            "matched_words": match["matched_words"],
                            "not_misconduct_proof": True,
                        },
                    }
                )
                if len(findings) >= 128:
                    break
            if len(findings) >= 128:
                break
        if len(findings) >= 128:
            break
    semantic_status = "unavailable_local_models"
    oversized_pairs = 0
    already_aligned = 0
    if passages and models.available("dense_retriever") and models.available("similarity_verifier"):
        semantic_candidates = []
        for user_span in user_passages[:32]:
            ranked, backend = dense.search(user_span.text, [p.text for _, p in passages], k=4)
            semantic_candidates.extend((user_span, i, score) for i, score in ranked)
        for query_span, i, similarity in semantic_candidates:
            context.check()
            if len(findings) >= 128:
                break
            source, span = passages[i]
            query_tokens = tokens(query_span.text)
            if query_tokens and any(
                finding["source_id"] == source.source_id
                and finding["category"] in {"EXACT_OVERLAP", "REORDERED_TEXT"}
                and finding["start_offset"] <= query_span.start_offset + query_tokens[0].start
                and finding["end_offset"] >= query_span.start_offset + query_tokens[-1].end
                and span.start_offset <= finding["source_start_offset"]
                and finding["source_end_offset"] <= span.end_offset
                for finding in findings
            ):
                # Lexical spans exclude surrounding punctuation. Compare lexical
                # coverage within this source passage before scoring a paraphrase.
                already_aligned += 1
                continue
            verification = pair_score(models, query_span.text, span.text)
            if verification is None:
                oversized_pairs += 1
                continue
            if verification < 0.8:
                continue
            if any(
                f["source_id"] == source.source_id
                and f["start_offset"] <= query_span.start_offset
                and f["end_offset"] >= query_span.end_offset
                for f in findings
            ):
                continue
            findings.append(
                {
                    "finding_id": f"match_{len(findings)}",
                    "document_id": document.document_id,
                    "revision": document.revision,
                    "offset_unit": "utf16_code_unit",
                    "start_offset": query_span.start_offset,
                    "end_offset": query_span.end_offset,
                    "source_id": source.source_id,
                    "source_title": source.title,
                    "source_url": source.url,
                    "source_start_offset": span.start_offset,
                    "source_end_offset": span.end_offset,
                    "category": "SEMANTIC_PARAPHRASE",
                    "similarity_score": similarity,
                    "verification_score": verification,
                    "retrieval_method": "bge_" + backend,
                    "confidence": None,
                    "diagnostics": {
                        "candidate_only": True,
                        "threshold": "proposed_not_calibrated",
                        "alignment": "whole_sentence_passage_not_exact_paraphrase_offsets",
                    },
                }
            )
        semantic_status = "experimental_uncalibrated"
    return {
        "status": "completed",
        "findings": findings,
        "source_count": len(sources),
        "diagnostics": {
            "semantic": semantic_status,
            "coverage_limited": len(user_passages) > 32 or len(findings) >= 128,
            "fingerprint_count": len(fingerprint_index),
            "minhash_candidates": len(minhash_candidates),
            "dense_token_windows": dense.window_count,
            "dense_pooling": "unique_token_weighted_window_embeddings",
            "semantic_pairs_over_token_budget": oversized_pairs,
            "semantic_candidates_already_aligned": already_aligned,
        },
    }
