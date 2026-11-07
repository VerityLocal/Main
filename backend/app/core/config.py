"""Fail-closed configuration without download-on-startup behavior."""

import os
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_DATA_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "VerityLocal"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOCAL_AI_", env_file=".env", extra="forbid", frozen=True
    )

    auth_token: SecretStr
    csrf_token: SecretStr
    bind_host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(default=8787, ge=1024, le=65535)
    allowed_origins: tuple[str, ...] = ()
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    request_timeout_seconds: float = Field(default=15, gt=0, le=120)
    body_timeout_seconds: float = Field(default=5, gt=0, le=30)
    rate_limit_per_minute: int = Field(default=120, ge=1, le=100_000)
    rate_limit_burst: int = Field(default=30, ge=1, le=10_000)
    max_concurrent_requests: int = Field(default=8, ge=1, le=128)
    max_documents: int = Field(default=128, ge=1, le=10_000)
    document_ttl_seconds: float = Field(default=1800, gt=0, le=86_400)
    config_dir: Path = PROJECT_ROOT / "configs"
    data_dir: Path = PRIVATE_DATA_ROOT / "data"
    model_cache: Path = PROJECT_ROOT / ".models"
    detector_checkpoint: Path | None = None
    analysis_timeout_seconds: float = Field(default=180, gt=0, le=900)
    max_analysis_requests: int = Field(default=32, ge=1, le=128)
    event_retention_seconds: int = Field(default=3600, ge=60, le=86400)
    external_search_enabled: bool = False

    @field_validator("auth_token", "csrf_token")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 32 or len(raw) > 256 or not raw.isascii() or any(c.isspace() for c in raw):
            raise ValueError("Secrets must be 32–256 non-whitespace ASCII characters")
        return value

    @model_validator(mode="after")
    def independent_secrets(self) -> Self:
        if self.auth_token.get_secret_value() == self.csrf_token.get_secret_value():
            raise ValueError("Authentication and CSRF secrets must differ")
        return self

    @field_validator("allowed_origins")
    @classmethod
    def exact_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if len(set(origins)) != len(origins):
            raise ValueError("Duplicate origins are not permitted")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError("Origins must have no path, credentials, query, or fragment")
            extension = bool(re.fullmatch(r"chrome-extension://[a-p]{32}", origin))
            local = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and parsed.netloc == parsed.netloc.lower()
                and origin == f"{parsed.scheme}://{parsed.netloc}"
                and "*" not in origin
            )
            if not (extension or local):
                raise ValueError("Only exact extension or loopback development origins are allowed")
            _ = parsed.port  # Validate port syntax.
        return origins


class HardwareConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"]
    gpu_allocated_ceiling_gib: float = Field(gt=0, lt=3.6)
    driver_free_headroom_mib: int = Field(ge=0)
    serialize_gpu_jobs: Literal[True]
    allow_training_with_inference: Literal[False]
    cpu_fallback: bool
    profiling_timeout_seconds: float = Field(gt=0, le=10)


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: str | None
    revision: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    tokenizer_revision: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    license: str | None
    enabled: bool

    @model_validator(mode="after")
    def enabled_requires_pins(self) -> Self:
        if self.enabled and not all(
            [self.model_id, self.revision, self.tokenizer_revision, self.license]
        ):
            raise ValueError("Enabled models require ID, exact revisions, and reviewed license")
        return self


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"]
    models: dict[str, ModelSpec]


class StylometryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"]
    feature_count: Literal[24]
    profile: Literal["light_v1", "full_v1"]
    mattr_window: Literal[50]
    richness_min_words: int = Field(ge=2)
    pos_min_transitions_per_group: int = Field(ge=1)
    reference_features_enabled: Literal[False]
    reference_context_tokens: int = Field(ge=1)
    normalization: Literal["training_valid_zscore"]
    invalid_json_value: None
    implementation_status: Literal["implemented_uncalibrated"]


class WinnowingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    k_gram_size: int = Field(ge=1)
    window_size: int = Field(ge=1)


class MinHashConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permutations: int = Field(ge=1)
    bands: int = Field(ge=1)
    rows: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_bands(self) -> Self:
        if self.bands * self.rows != self.permutations:
            raise ValueError("MinHash bands times rows must equal permutations")
        return self


class DenseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_tokens: int = Field(ge=1, le=512)
    normalize_embeddings: Literal[True]
    similarity: Literal["cosine"]


class RrfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    k0: int = Field(ge=1)


class ExternalSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool
    requires_explicit_consent: Literal[True]


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"]
    winnowing: WinnowingConfig
    minhash: MinHashConfig
    dense: DenseConfig
    rrf: RrfConfig
    external_search: ExternalSearchConfig


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"]
    seed: int = Field(ge=0)
    splits: tuple[Literal["train", "validation", "calibration", "final_test"], ...]
    leakage_groups: tuple[str, ...]
    ai_metrics: tuple[str, ...]
    similarity_metrics: tuple[str, ...]
    claim_metrics: tuple[str, ...]
    benchmark_requires_hardware_metadata: Literal[True]
    benchmark_results_available: Literal[False]

    @model_validator(mode="after")
    def four_separate_splits(self) -> Self:
        if len(self.splits) != 4 or set(self.splits) != {
            "train",
            "validation",
            "calibration",
            "final_test",
        }:
            raise ValueError("Four distinct dataset splits are required")
        return self


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hardware: HardwareConfig
    models: ModelsConfig
    stylometry: StylometryConfig
    retrieval: RetrievalConfig
    evaluation: EvaluationConfig


def load_platform_config(directory: Path) -> PlatformConfig:
    def load(name: str) -> dict:
        with (directory / name).open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if not isinstance(data, dict):
            raise ValueError("Configuration files must contain objects")
        return data

    return PlatformConfig(
        hardware=load("hardware.yaml"),
        models=load("models.yaml"),
        stylometry=load("stylometry.yaml"),
        retrieval=load("retrieval.yaml"),
        evaluation=load("evaluation.yaml"),
    )
