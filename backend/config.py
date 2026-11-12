"""Validated local configuration; no network access or automatic downloads."""

from dataclasses import dataclass, field
import math
import os
import re
from pathlib import Path
import tempfile
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DISCLAIMER = (
    "AI-detector scores are probabilistic and may produce false positives. "
    "They are not proof of AI authorship or academic misconduct. "
    "The code detector is an experimental synthetic-style classifier."
    " Both detectors are unvalidated for university submissions."
)


@dataclass(frozen=True)
class Settings:
    models_dir: Path = PROJECT_ROOT / "models"
    device: str = "cpu"
    max_tokens: int = 512
    batch_size: int = 4
    torch_threads: int = 4
    threshold: float = 0.5
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pages: int = 500
    max_extracted_chars: int = 2_000_000
    max_chunks: int = 4096
    max_active_jobs: int = 3
    max_retained_jobs: int = 16
    result_ttl_seconds: int = 900
    upload_timeout_seconds: int = 30
    extraction_timeout_seconds: int = 120
    job_timeout_seconds: int = 600
    max_render_pixels: int = 8_000_000
    max_ocr_regions_per_page: int = 20
    min_text_chunk_tokens: int = 80
    min_text_total_tokens: int = 150
    min_code_chunk_tokens: int = 40
    min_code_total_tokens: int = 80
    docling_assets_dir: Path | None = None
    extraction_python: Path | None = None
    tesseract_command: str = "tesseract"
    tessdata_dir: Path | None = None
    auth_token: str | None = field(default=None, repr=False)
    extension_id: str | None = None
    temp_dir: Path = Path(tempfile.gettempdir()) / "verity-local"

    def __post_init__(self) -> None:
        object.__setattr__(self, "models_dir", Path(self.models_dir).expanduser().resolve())
        if self.device not in {"cpu", "mps", "cuda"}:
            raise ValueError("PDF_AI_DEVICE must be cpu, mps, or cuda")
        for name, value, upper in (
            ("max_tokens", self.max_tokens, 512),
            ("batch_size", self.batch_size, 64),
            ("torch_threads", self.torch_threads, 64),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer between 1 and {upper}")
        if self.max_tokens < 8:
            raise ValueError("max_tokens must be at least 8, including special tokens")
        if type(self.threshold) not in {int, float} or not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite and between 0 and 1")
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be finite and between 0 and 1")
        for name in (
            "max_upload_bytes", "max_pages", "max_extracted_chars", "max_chunks",
            "max_active_jobs", "max_retained_jobs", "result_ttl_seconds",
            "upload_timeout_seconds", "extraction_timeout_seconds", "job_timeout_seconds",
            "max_render_pixels", "max_ocr_regions_per_page", "min_text_chunk_tokens",
            "min_text_total_tokens", "min_code_chunk_tokens", "min_code_total_tokens",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_retained_jobs < self.max_active_jobs:
            raise ValueError("max_retained_jobs must be at least max_active_jobs")
        object.__setattr__(self, "temp_dir", Path(self.temp_dir).expanduser().resolve())
        if self.docling_assets_dir is not None:
            object.__setattr__(self, "docling_assets_dir", Path(self.docling_assets_dir).expanduser().resolve())
        for name in ("extraction_python", "tessdata_dir"):
            if getattr(self, name) is not None:
                value = Path(getattr(self, name)).expanduser()
                # Resolving a venv's python symlink selects the base interpreter
                # and silently loses the isolated parser site-packages.
                object.__setattr__(self, name, value.absolute() if name == 'extraction_python' else value.resolve())
        if self.auth_token is not None and (len(self.auth_token) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", self.auth_token)):
            raise ValueError("PDF_AI_AUTH_TOKEN must be at least 32 URL-safe characters")
        if self.extension_id is not None and not re.fullmatch(r"[a-p]{32}", self.extension_id):
            raise ValueError("PDF_AI_EXTENSION_ID must be the exact 32-character Chrome/Edge extension ID")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        return cls(
            models_dir=Path(env.get("PDF_AI_MODELS_DIR", str(PROJECT_ROOT / "models"))),
            device=env.get("PDF_AI_DEVICE", "cpu"),
            max_tokens=int(env.get("PDF_AI_MAX_TOKENS", "512")),
            batch_size=int(env.get("PDF_AI_BATCH_SIZE", "4")),
            torch_threads=int(env.get("PDF_AI_TORCH_THREADS", "4")),
            threshold=float(env.get("PDF_AI_THRESHOLD", "0.5")),
            **{
                name: int(env.get("PDF_AI_" + name.upper(), str(field.default)))
                for name, field in cls.__dataclass_fields__.items()
                if field.type is int and name not in {"max_tokens", "batch_size", "torch_threads"}
            },
            docling_assets_dir=Path(env["PDF_AI_DOCLING_ASSETS_DIR"]) if env.get("PDF_AI_DOCLING_ASSETS_DIR") else None,
            temp_dir=Path(env.get("PDF_AI_TEMP_DIR", str(cls.__dataclass_fields__["temp_dir"].default))),
            extraction_python=Path(env["PDF_AI_EXTRACTION_PYTHON"]) if env.get("PDF_AI_EXTRACTION_PYTHON") else None,
            tesseract_command=env.get("PDF_AI_TESSERACT_COMMAND", "tesseract"),
            tessdata_dir=Path(env["PDF_AI_TESSDATA_DIR"]) if env.get("PDF_AI_TESSDATA_DIR") else None,
            auth_token=env.get("PDF_AI_AUTH_TOKEN") or None,
            extension_id=env.get("PDF_AI_EXTENSION_ID") or None,
        )
