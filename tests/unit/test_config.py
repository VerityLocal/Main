import pytest
from pydantic import ValidationError

from backend.app.core.config import (
    PROJECT_ROOT,
    HardwareConfig,
    MinHashConfig,
    ModelSpec,
    Settings,
    load_platform_config,
)
from backend.scripts.init_local import initialize


def test_all_configuration_files_validate():
    config = load_platform_config(PROJECT_ROOT / "configs")
    assert config.stylometry.feature_count == 24
    assert config.retrieval.minhash.permutations == 128
    # Explicit local downloads may enable models in this configuration.
    assert {
        "ai_backbone",
        "dense_retriever",
        "similarity_verifier",
        "nli_verifier",
        "cross_encoder",
    } <= config.models.models.keys()
    assert config.hardware.gpu_allocated_ceiling_gib < 3.6


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_token": "short"},
        {"csrf_token": "bad secret " * 5},
        {"bind_host": "0.0.0.0"},
        {"auth_token": "x" * 40, "csrf_token": "x" * 40},
        {"max_request_bytes": 1},
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("null",)},
        {"allowed_origins": ("https://evil.example",)},
        {"allowed_origins": ("http://localhost:8787/path",)},
        {"allowed_origins": ("http://user@localhost:8787",)},
        {"allowed_origins": ("chrome-extension://invalid",)},
        {"allowed_origins": ("http://localhost:bad",)},
        {"allowed_origins": ("http://localhost:8787?",)},
        {"allowed_origins": ("http://localhost:8787#",)},
    ],
)
def test_invalid_settings_fail_closed(settings_factory, overrides):
    with pytest.raises(ValidationError):
        settings_factory(**overrides)


def test_credentials_do_not_appear_in_settings_repr(settings):
    assert settings.auth_token.get_secret_value() not in repr(settings)
    assert settings.csrf_token.get_secret_value() not in repr(settings)


def test_initialization_uses_random_independent_secrets_and_never_overwrites(tmp_path):
    path = tmp_path / ".env"
    initialize(path)
    contents = path.read_text(encoding="utf-8")
    loaded = Settings(_env_file=path)
    assert loaded.auth_token != loaded.csrf_token
    assert len(loaded.auth_token.get_secret_value()) >= 48
    with pytest.raises(FileExistsError):
        initialize(path)
    assert path.read_text(encoding="utf-8") == contents


def test_enabled_model_requires_exact_pins():
    values = dict(model_id="m", revision=None, tokenizer_revision=None, license=None, enabled=True)
    with pytest.raises(ValidationError):
        ModelSpec(**values)
    with pytest.raises(ValidationError):
        ModelSpec(**{**values, "revision": "main", "enabled": False})
    pinned = ModelSpec(
        model_id="m",
        revision="a" * 40,
        tokenizer_revision="b" * 40,
        license="reviewed-license",
        enabled=True,
    )
    assert pinned.enabled


def test_minhash_and_hardware_invariants():
    with pytest.raises(ValidationError):
        MinHashConfig(permutations=128, bands=15, rows=8)
    values = load_platform_config(PROJECT_ROOT / "configs").hardware.model_dump()
    with pytest.raises(ValidationError):
        HardwareConfig(**{**values, "gpu_allocated_ceiling_gib": 3.6})
