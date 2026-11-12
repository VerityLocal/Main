"""Local model startup, bounded PDF uploads, and asynchronous analysis progress."""

import asyncio
from contextlib import asynccontextmanager
import math
import secrets

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend import __version__
from backend.analysis.capabilities import capabilities
from backend.analysis.extraction import validate_pdf
from backend.analysis.jobs import JobManager
from backend.analysis.pipeline import AnalysisPipeline
from backend.analysis.types import AnalysisError
from backend.analysis.source import FORMATS, decode_source
from backend.config import Settings
from backend.detectors.loaders import load_detector
from backend.detectors.runtime import ModelRuntime


def create_app(settings: Settings | None = None, *, loader=load_detector, pipeline_factory=AnalysisPipeline) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = ModelRuntime(settings, loader)
        application.state.runtime = runtime
        jobs = JobManager(settings, pipeline_factory(settings,runtime))
        application.state.jobs = jobs
        try:
            await asyncio.to_thread(runtime.initialize)
            jobs.start()
            yield
        finally:
            await asyncio.to_thread(jobs.close)
            runtime.close()

    application = FastAPI(
        title="Verity Local", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None,
        description="Local PDF analysis with separate prose/code signals and explicit coverage.",
    )
    application.state.runtime = ModelRuntime(settings, loader)
    application.state.jobs = None
    application.state.settings = settings

    @application.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origin = f'chrome-extension://{settings.extension_id}' if settings.extension_id else None
        if origin and origin != allowed_origin:
            response = JSONResponse({'detail':'Browser origin is not authorized.'}, status_code=403)
        elif request.method == 'OPTIONS':
            method = request.headers.get('access-control-request-method', '')
            headers = {value.strip().lower() for value in request.headers.get('access-control-request-headers', '').split(',') if value.strip()}
            if not origin or origin != allowed_origin or method not in {'GET','POST'} or not headers <= {'authorization','content-type'}:
                response = JSONResponse({'detail':'Preflight is not authorized.'}, status_code=403)
            else:
                response = JSONResponse({}, headers={'Access-Control-Allow-Methods':'GET, POST',
                    'Access-Control-Allow-Headers':'Authorization, Content-Type', 'Access-Control-Max-Age':'600',
                    'Access-Control-Allow-Private-Network':'true'})
        elif not settings.auth_token:
            response = JSONResponse({'detail':'Configure PDF_AI_AUTH_TOKEN locally before using the service.'},status_code=503)
        else:
            supplied = request.headers.get('authorization', '')
            if not secrets.compare_digest(supplied.encode(), ('Bearer '+settings.auth_token).encode()):
                response = JSONResponse({'detail':'Valid bearer token required.'},status_code=401,
                                        headers={'WWW-Authenticate':'Bearer'})
            else:
                response = await call_next(request)
        if origin and origin == allowed_origin:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @application.get("/health")
    def health() -> JSONResponse:
        payload = application.state.runtime.health()
        caps = capabilities(settings)
        jobs = application.state.jobs
        payload.update(phase="pdf_analysis",pipeline=caps,
                       supported_upload_formats=list(FORMATS),
                       analysis_available=bool(jobs and jobs.accepting and
                                               any(model["status"]=="ready" for model in payload["models"].values())))
        return JSONResponse(payload, status_code=200 if payload["ready"] else 503,
                            headers={"Cache-Control": "no-store"})

    @application.post("/analyze",status_code=202)
    async def analyze(request: Request, threshold: float | None = Query(default=None,ge=0,le=1),
                      format: str | None = Query(default=None)):
        media = request.headers.get('content-type','').split(';',1)[0].strip().lower()
        inferred = next((kind for kind, mime in FORMATS.items() if mime == media), None)
        file_format = format or inferred
        if file_format not in FORMATS or not (media == FORMATS[file_format] or (media=='text/plain' and file_format!='pdf')):
            raise HTTPException(415,'Send raw PDF, UTF-8 text, Python, or JavaScript bytes with the matching Content-Type/format.')
        value = settings.threshold if threshold is None else threshold
        if not math.isfinite(value):
            raise HTTPException(422,"Threshold must be finite.")
        length = request.headers.get("content-length")
        if length:
            try:
                count = int(length)
            except ValueError:
                raise HTTPException(400,"Invalid Content-Length.")
            if count < 0 or count > settings.max_upload_bytes:
                raise HTTPException(413,"PDF exceeds the upload limit.")
        jobs = application.state.jobs
        ready = application.state.runtime.health()
        if not jobs or (file_format=='pdf' and not capabilities(settings)["native_available"]) or not any(
                model["status"]=="ready" for model in ready["models"].values()):
            raise HTTPException(503,"PDF tools or all detectors are unavailable; check /health.")
        try:
            job = jobs.reserve(value, file_format)
        except AnalysisError as exc:
            raise HTTPException(429 if exc.code=="queue_full" else 503,str(exc),headers={"Retry-After":"5"})
        try:
            received = 0
            async with asyncio.timeout(settings.upload_timeout_seconds):
                with job.path.open("wb") as handle:
                    async for block in request.stream():
                        received += len(block)
                        if received > settings.max_upload_bytes:
                            raise HTTPException(413,"PDF exceeds the upload limit.")
                        await asyncio.to_thread(handle.write, block)
            data = await asyncio.to_thread(job.path.read_bytes)
            if file_format == 'pdf':
                validate_pdf(data,settings)
            else:
                decode_source(data,settings)
            jobs.enqueue(job.id)
        except TimeoutError:
            jobs.abandon(job.id)
            raise HTTPException(408,"PDF upload timed out.")
        except AnalysisError as exc:
            jobs.abandon(job.id)
            raise HTTPException(400,str(exc))
        except BaseException:
            jobs.abandon(job.id)
            raise
        return {"job_id":job.id,"status":"queued","status_url":f"/analyze/{job.id}"}

    @application.get("/analyze/{job_id}")
    def analysis_status(job_id: str):
        jobs = application.state.jobs
        result = jobs.snapshot(job_id) if jobs is not None else None
        if result is None:
            raise HTTPException(404,"Unknown, expired, or evicted analysis job.")
        return result

    # Host validation must also wrap preflight and authentication error responses.
    application.add_middleware(TrustedHostMiddleware,allowed_hosts=["localhost","127.0.0.1","[::1]"])
    return application


app = create_app()
