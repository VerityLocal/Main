"""Secure local FastAPI factory and loopback-only launcher."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from backend.app.api.v1.routes import router
from backend.app.core.config import Settings, load_platform_config
from backend.app.core.logging import configure_logging
from backend.app.core.resource_manager import GpuMemoryGuard, HardwareSnapshot
from backend.app.core.security import LocalSecurityMiddleware, safe_error
from backend.app.runtime.inference_queue import InferenceQueue
from backend.app.runtime.profiling import profile_hardware
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.document_manager import DocumentManager
from backend.app.services.event_manager import EventManager
from backend.app.services.model_manager import ModelManager


def create_app(
    settings: Settings | None = None,
    hardware_profiler: Callable[[float], HardwareSnapshot] = profile_hardware,
) -> FastAPI:
    settings = settings or Settings()
    config = load_platform_config(settings.config_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        app.state.hardware = await asyncio.to_thread(
            hardware_profiler, config.hardware.profiling_timeout_seconds
        )
        logging.getLogger("local_ai").info("hardware_snapshot_recorded")
        await app.state.inference.start()
        try:
            yield
        finally:
            await app.state.inference.stop()
            app.state.models.unload()
            app.state.events.close()
            app.state.corpus.close()
            app.state.documents.clear()
            logging.getLogger("local_ai").info("local_server_stopped")

    app = FastAPI(
        title="Local AI Analysis Platform",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.platform_config = config
    app.state.documents = DocumentManager(settings.max_documents, settings.document_ttl_seconds)
    app.state.gpu_guard = GpuMemoryGuard(config.hardware.gpu_allocated_ceiling_gib)
    from backend.app.retrieval.corpus import Corpus

    app.state.corpus = Corpus(settings.data_dir / "corpus.sqlite3")
    app.state.events = EventManager(
        settings.data_dir / "events.sqlite3",
        settings.max_analysis_requests,
        settings.event_retention_seconds,
    )
    app.state.models = ModelManager(settings, config)
    runner = AnalysisService(
        app.state.documents, app.state.events, app.state.corpus, app.state.models, config, settings
    )
    app.state.inference = InferenceQueue(
        runner, app.state.events, settings.analysis_timeout_seconds, settings.max_analysis_requests
    )
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _error: RequestValidationError):
        return safe_error(
            422,
            "invalid_request",
            "Request does not match the canonical schema",
            request.state.request_id,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return safe_error(
            error.status_code,
            "http_error",
            "Requested operation is unavailable",
            request.state.request_id,
        )

    return app


def run() -> None:
    import uvicorn

    try:
        settings = Settings()
        app = create_app(settings)
    except (ValueError, OSError):
        # Pydantic errors may include input values; do not print their repr.
        raise SystemExit("Invalid configuration. Generate .env and review configs/.") from None
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
        timeout_keep_alive=5,
        limit_concurrency=settings.max_concurrent_requests + 4,
        h11_max_incomplete_event_size=16_384,
    )


if __name__ == "__main__":
    run()
