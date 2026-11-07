"""Authenticated analyses, bounded SSE replay and local source management."""

import asyncio
import time

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from backend.app.core.security import safe_error
from backend.app.schemas.analysis import AnalysisRequest, Source
from backend.app.schemas.api import HealthResponse, RegistrationResponse
from backend.app.schemas.document import Document
from backend.app.schemas.extraction import TextAnalysisRequest
from backend.app.services.document_manager import RegistryFull, RevisionConflict

router = APIRouter(prefix="/api/v1")


@router.post("/analyses/text", status_code=202)
async def start_extracted_analysis(body: "TextAnalysisRequest", request: Request):
    try:
        canonical = body.extraction.canonical()
        analysis = AnalysisRequest(
            document=canonical,
            engines=body.engines,
            external_search_consent=body.external_search_consent,
        )
    except ValueError:
        return safe_error(
            422,
            "invalid_extraction",
            "Extraction violates the canonical document contract",
            request.state.request_id,
        )
    return await start_analysis(analysis, request)


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        hardware=request.app.state.hardware,
        components={
            "ai_detection": "requires_trained_checkpoint"
            if request.app.state.settings.detector_checkpoint is None
            else "configured_checkpoint",
            "plagiarism": "lexical_ready_semantic_optional",
            "claim_verification": "retrieval_ready_nli_optional_experimental",
            "sse_transport": "ready_reconnectable",
            "browser_extension": "see_extension_compatibility_report",
        },
        gpu_allocated_ceiling_bytes=request.app.state.gpu_guard.ceiling_bytes,
    )


@router.post("/documents/register", response_model=RegistrationResponse)
def register_document(document: Document, request: Request):
    try:
        changed = request.app.state.documents.register(document)
    except RevisionConflict:
        return safe_error(
            409,
            "revision_conflict",
            "Document revision conflicts with registered content",
            request.state.request_id,
        )
    except RegistryFull:
        return safe_error(
            503, "registry_full", "Document registry capacity reached", request.state.request_id
        )
    return RegistrationResponse(
        document_id=document.document_id, revision=document.revision, changed=changed
    )


@router.post("/analyses", status_code=202)
async def start_analysis(body: AnalysisRequest, request: Request):
    identifier = None
    if body.external_search_consent and not (
        request.app.state.settings.external_search_enabled
        and request.app.state.platform_config.retrieval.external_search.enabled
    ):
        return safe_error(
            403,
            "external_search_disabled",
            "External search is disabled by local policy",
            request.state.request_id,
        )
    try:
        request.app.state.documents.register(body.document)
        identifier = request.app.state.events.create(body.document)
        await request.app.state.inference.submit(identifier, body)
        return {
            "request_id": identifier,
            "document_id": body.document.document_id,
            "document_revision": body.document.revision,
            "offset_unit": "utf16_code_unit",
        }
    except RevisionConflict:
        return safe_error(
            409, "revision_conflict", "Use the current document revision", request.state.request_id
        )
    except (RegistryFull, RuntimeError):
        if identifier:
            request.app.state.events.append(
                identifier,
                "analysis.error",
                {
                    "code": "busy",
                    "message": "Inference queue is full; resubmit later",
                },
            )
        return safe_error(503, "busy", "Local analysis capacity reached", request.state.request_id)


@router.get("/analyses/{identifier}")
def analysis_status(identifier: str, request: Request):
    try:
        return request.app.state.events.get(identifier)
    except KeyError:
        return safe_error(
            410, "history_unavailable", "Resubmit the current document", request.state.request_id
        )


@router.get("/analyses/{identifier}/events")
async def analysis_events(
    identifier: str,
    request: Request,
    last_event_id: str = Header(default="0", alias="Last-Event-ID"),
):
    try:
        request.app.state.events.get(identifier)
    except KeyError:
        return safe_error(
            410, "history_unavailable", "Resubmit the current document", request.state.request_id
        )
    if not last_event_id.isascii() or not last_event_id.isdecimal() or len(last_event_id) > 6:
        return safe_error(
            400,
            "invalid_cursor",
            "Last-Event-ID must be a sequence number",
            request.state.request_id,
        )
    after = int(last_event_id)
    history = request.app.state.events.replay(identifier)
    latest = history[-1][1].sequence if history else 0
    if after > latest:
        return safe_error(
            409,
            "invalid_cursor",
            "Event cursor is ahead of request history",
            request.state.request_id,
        )

    async def stream():
        nonlocal after
        deadline = time.monotonic() + min(
            8, request.app.state.settings.request_timeout_seconds * 0.7
        )
        while time.monotonic() < deadline:
            for name, event in request.app.state.events.replay(identifier, after):
                after = event.sequence
                yield event.to_sse(name)
            if request.app.state.events.get(identifier)["terminal"]:
                return
            if await request.is_disconnected():
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@router.post("/analyses/{identifier}/cancel")
def cancel_analysis(identifier: str, request: Request):
    try:
        request.app.state.events.get(identifier)
        request.app.state.inference.cancel(identifier)
        return {"cancelled": True}
    except KeyError:
        return safe_error(
            410, "history_unavailable", "Request history is unavailable", request.state.request_id
        )


@router.get("/models/status")
def model_status(request: Request):
    return {
        "models": request.app.state.models.status(),
        "device": "cpu",
        "gpu_jobs_enabled": False,
        "external_search_enabled": (
            request.app.state.settings.external_search_enabled
            and request.app.state.platform_config.retrieval.external_search.enabled
        ),
        "detector_checkpoint_configured": request.app.state.settings.detector_checkpoint
        is not None,
    }


@router.post("/models/unload")
def unload_models(request: Request):
    if request.app.state.models.references:
        return safe_error(409, "model_busy", "Model is actively in use", request.state.request_id)
    request.app.state.models.unload()
    return {"unloaded": True}


@router.get("/sources")
def list_sources(request: Request):
    return {
        "sources": [
            {
                "source_id": s.source_id,
                "title": s.title,
                "url": s.url,
                "characters": len(s.text),
                "reliability": s.reliability,
            }
            for s in request.app.state.corpus.all()
        ]
    }


@router.post("/sources", status_code=201)
def add_source(source: Source, request: Request):
    try:
        request.app.state.corpus.add(source)
        return {"source_id": source.source_id, "stored_locally": True}
    except ValueError:
        return safe_error(
            422,
            "source_limit",
            "Invalid source or corpus capacity reached",
            request.state.request_id,
        )


@router.post("/sources/{identifier}/remove")
def remove_source(identifier: str, request: Request):
    request.app.state.corpus.remove(identifier)
    return {"removed": True}
