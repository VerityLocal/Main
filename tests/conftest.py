"""Synthetic test hardware is not a benchmark of the current machine."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.resource_manager import HardwareSnapshot
from backend.app.document.builder import build_document
from backend.app.main import create_app

AUTH_TOKEN = "test_auth_" + "a" * 48
CSRF_TOKEN = "test_csrf_" + "b" * 48
EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


@pytest.fixture
def settings_factory(tmp_path):
    def factory(**overrides):
        values = dict(
            auth_token=AUTH_TOKEN,
            csrf_token=CSRF_TOKEN,
            allowed_origins=(EXTENSION_ORIGIN,),
            _env_file=None,
            data_dir=tmp_path / "data",
            model_cache=tmp_path / "models",
        )
        values.update(overrides)
        return Settings(**values)

    return factory


@pytest.fixture
def settings(settings_factory):
    return settings_factory()


@pytest.fixture
def hardware():
    return HardwareSnapshot(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        platform="synthetic_test_platform",
        python_version="3.11",
        cpu_model="synthetic_test_cpu",
        logical_cpu_count=4,
        physical_cpu_count=2,
        system_ram_total_bytes=8 * 1024**3,
        system_ram_available_bytes=4 * 1024**3,
        process_rss_bytes=32 * 1024**2,
        torch_installed=False,
        torch_version=None,
        torch_cuda_build_version=None,
        cuda_available=None,
        diagnostics=("synthetic_fixture_not_measured_hardware",),
    )


@pytest.fixture
def app(settings, hardware):
    return create_app(settings, hardware_profiler=lambda _timeout: hardware)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8787") as instance:
        yield instance


@pytest.fixture
def auth_headers():
    return {"X-Local-Token": AUTH_TOKEN, "X-CSRF-Token": CSRF_TOKEN}


@pytest.fixture
def document():
    return build_document(
        ["Café 😀 is Unicode.", "A second paragraph."],
        document_id="doc_test",
        revision=2,
        language="en",
        block_ids=["block_a", "block_b"],
    )
