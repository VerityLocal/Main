"""Probe optional tools without importing models or downloading assets."""

import importlib.util
from pathlib import Path
import shutil
import json
import subprocess
from functools import lru_cache

from backend.config import Settings


@lru_cache(maxsize=32)
def capabilities(settings: Settings) -> dict:
    if settings.extraction_python:
        # Probe the isolated parser environment without importing its packages in
        # the model process. Failure must not falsely claim native/OCR support.
        probe_settings = {'tesseract_command': settings.tesseract_command,
                          'docling_assets_dir': str(settings.docling_assets_dir) if settings.docling_assets_dir else None,
                          'tessdata_dir': str(settings.tessdata_dir) if settings.tessdata_dir else None}
        code = ("import json; "
                "from backend.config import Settings; from backend.analysis.capabilities import capabilities; "
                "print(json.dumps(capabilities(Settings(**" + repr(probe_settings) + "))))")
        try:
            from backend.config import PROJECT_ROOT
            result = subprocess.run([str(settings.extraction_python), '-B', '-c', code], cwd=PROJECT_ROOT,
                                    capture_output=True, text=True, timeout=15, check=True)
            return json.loads(result.stdout)
        except Exception:
            return {'native_available': False, 'native_engines': [], 'ocr_configured': False,
                    'docling_configured': False, 'automatic_downloads': False,
                    'error': 'Isolated extraction interpreter could not be probed.'}
    native = [name for name in ("pymupdf", "pdfplumber") if importlib.util.find_spec(name) is not None]
    assets = settings.docling_assets_dir
    docling = importlib.util.find_spec("docling") is not None
    configured = bool(assets and (Path(assets) / "approved-manifest.json").is_file())
    tesseract = shutil.which(settings.tesseract_command) is not None
    renderer = bool(native) and ("pymupdf" in native or importlib.util.find_spec("pypdfium2") is not None)
    return {
        "native_available": bool(native), "native_engines": native,
        "docling_configured": docling and configured,
        "docling_note": "Requires installed Docling and explicitly approved, hash-manifested local assets.",
        "ocr_configured": tesseract and renderer,
        "ocr_note": "Requires local Tesseract, eng language data, and a renderer; checked again per job.",
        "automatic_downloads": False,
    }
