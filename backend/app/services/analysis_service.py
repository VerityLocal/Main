"""Independent engines; stale emissions are rejected and errors are isolated."""

import asyncio

from backend.app.document.chunking import sentence_spans
from backend.app.engines.ai_detection.inference import analyze as detect_ai
from backend.app.engines.hallucination.inference import analyze as verify_claims
from backend.app.engines.hallucination.web_evidence import search_wikipedia
from backend.app.engines.plagiarism.inference import analyze as compare_sources
from backend.app.runtime.inference_queue import AnalysisAborted


class AnalysisService:
    def __init__(self, documents, events, corpus, models, config, settings):
        self.documents, self.events, self.corpus = documents, events, corpus
        self.models, self.config, self.settings = models, config, settings

    def run(self, identifier, request, context):
        document = request.document

        def emit(name, payload):
            context.check()
            if not self.documents.is_current(document.document_id, document.revision):
                raise AnalysisAborted("stale_revision")
            self.events.append(identifier, name, payload)

        try:
            emit("analysis.started", {"engines": list(request.engines), "device": "cpu"})
            sources = self.corpus.all()
            for engine in request.engines:
                context.check()
                try:
                    result = self.run_engine(engine, request, sources, context, emit)
                except AnalysisAborted:
                    raise
                except Exception:
                    # Never include document/model exception repr in API events.
                    result = {
                        "status": "unavailable",
                        "findings": [],
                        "reason": "Engine failed; check local model/profile configuration",
                    }
                emit(f"{engine}.completed", result)
            emit("analysis.completed", {"status": "completed"})
        except AnalysisAborted as error:
            self.events.append(
                identifier,
                "analysis.error",
                {
                    "code": str(error),
                    "message": "Analysis stopped; use the current document revision",
                },
            )

    def run_engine(self, engine, request, sources, context, emit):
        document = request.document
        if engine == "ai_detection":
            return detect_ai(document, self.models, self.settings, context)
        if engine == "plagiarism":
            return compare_sources(document, sources, self.models, self.config, context)
        external_status = "disabled_no_network"
        enabled = (
            self.settings.external_search_enabled and self.config.retrieval.external_search.enabled
        )
        if request.external_search_consent and enabled:
            extra = []
            for span in sentence_spans(document.extracted_text)[:3]:
                context.check()
                extra.extend(asyncio.run(search_wikipedia(span.text, consent=True, enabled=True)))
            sources = list({s.source_id: s for s in sources + extra}.values())
            external_status = "wikipedia_opt_in_unrated_evidence"
        result = verify_claims(
            document,
            sources,
            self.models,
            self.config,
            context,
            lambda payload: emit("claim_verification.partial", payload),
        )
        result["diagnostics"]["external_search"] = external_status
        # Detailed claims already have individual replayable partial events.
        # Avoid duplicating many evidence passages into a >512 KiB final frame.
        result["streamed_finding_count"] = len(result["findings"])
        result["findings"] = []
        return result
