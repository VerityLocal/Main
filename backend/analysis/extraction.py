"""Bounded subprocess wrapper, keeping PDF parser/OCR work outside the API process."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from backend.analysis.types import AnalysisError, Document
from backend.config import PROJECT_ROOT, Settings


def validate_pdf(data: bytes, settings: Settings):
    if len(data) > settings.max_upload_bytes:
        raise AnalysisError("upload_limit", "PDF exceeds the upload limit.")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
        raise AnalysisError("invalid_pdf", "Expected complete PDF bytes, not a URL, filename, or HTML page.")


def extract_pdf(path: Path, settings: Settings, progress=lambda *args: None, check=lambda: None) -> Document:
    request, output = path.parent / "extract-request.json", path.parent / "extraction.json"
    config = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(settings).items()}
    # Parser subprocesses do not need API credentials.
    config["auth_token"] = None
    config["extraction_python"] = None
    request.write_text(json.dumps({"input": str(path), "output": str(output), "settings": config}))
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "HF_HOME": str(path.parent/"hf-cache"), "XDG_CACHE_HOME": str(path.parent/"cache")}
    process = subprocess.Popen([str(settings.extraction_python or sys.executable), "-m", "backend.analysis.extract_worker", str(request)],
                               cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + settings.extraction_timeout_seconds
    buffer = b""
    try:
        while process.poll() is None:
            check()
            if time.monotonic() > deadline:
                raise AnalysisError("extraction_timeout", "PDF extraction/OCR timed out; no partial document was scored.")
            for key, _ in selector.select(.2):
                block = os.read(key.fileobj.fileno(), 16384)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                buffer = (buffer + block)[-65536:]
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.startswith(b"PDF_AI_EVENT "):
                        event = json.loads(line[len(b"PDF_AI_EVENT "):])
                        progress(event["stage"], event["current"], event["total"])
        if process.returncode != 0 or not output.is_file():
            raise AnalysisError("extraction_failed", "PDF parser process failed; no scores were produced.")
        if output.stat().st_size > settings.max_extracted_chars*16 + settings.max_pages*4096:
            raise AnalysisError("content_limit", "Extraction metadata exceeds the resource limit.")
        result = json.loads(output.read_text(encoding="utf-8"))
        if "error" in result:
            raise AnalysisError(**result["error"])
        return Document.from_dict(result["document"])
    finally:
        selector.close()
        # Includes a still-running OCR grandchild in the same private process group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)
        process.stdout.close()
