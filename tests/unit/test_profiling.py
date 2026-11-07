import subprocess
from importlib import metadata
from types import SimpleNamespace

import pytest

from backend.app.runtime import profiling


def test_driver_tool_absence(monkeypatch):
    monkeypatch.setattr(profiling.shutil, "which", lambda _name: None)
    assert profiling.probe_driver() == ((), ("nvidia_smi_unavailable",))


def test_real_driver_units_and_separate_metrics(monkeypatch):
    monkeypatch.setattr(profiling.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        profiling.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="0, Example GPU, 555.1, 4096, 3072, 1024\n"
        ),
    )
    devices, diagnostics = profiling.probe_driver()
    assert not diagnostics
    assert devices[0].total_bytes == 4096 * 1024**2
    assert devices[0].free_bytes == 3072 * 1024**2
    assert devices[0].used_bytes == 1024 * 1024**2


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("nvidia-smi", 1), OSError("private data")]
)
def test_driver_failure_is_safe(monkeypatch, failure):
    monkeypatch.setattr(profiling.shutil, "which", lambda _name: "nvidia-smi")

    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(profiling.subprocess, "run", fail)
    devices, diagnostics = profiling.probe_driver()
    assert not devices
    assert diagnostics in [("nvidia_smi_timeout",), ("nvidia_smi_probe_failed",)]
    assert "private data" not in str(diagnostics)


def test_torch_absence_is_unknown_not_false(monkeypatch):
    def absent(_name):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(profiling.metadata, "version", absent)
    data = profiling.probe_torch()
    assert not data["torch_installed"]
    assert data["cuda_available"] is None


def test_optional_torch_import_failure_is_safe(monkeypatch):
    monkeypatch.setattr(profiling.metadata, "version", lambda _name: "test")

    def fail(_name):
        raise RuntimeError("private binary path")

    monkeypatch.setattr(profiling.importlib, "import_module", fail)
    data = profiling.probe_torch()
    assert data["torch_installed"]
    assert data["cuda_available"] is None
    assert "private binary path" not in str(data)


def test_cpu_only_torch_build(monkeypatch):
    monkeypatch.setattr(profiling.metadata, "version", lambda _name: "test")
    fake = SimpleNamespace(
        version=SimpleNamespace(cuda=None), cuda=SimpleNamespace(is_available=lambda: False)
    )
    monkeypatch.setattr(profiling.importlib, "import_module", lambda _name: fake)
    assert profiling.probe_torch()["cuda_available"] is False


def test_hardware_snapshot_real_ram_cpu_with_mocked_gpu(monkeypatch):
    monkeypatch.setattr(profiling, "probe_driver", lambda _timeout: ((), ()))
    monkeypatch.setattr(
        profiling,
        "probe_torch",
        lambda: {
            "torch_installed": False,
            "torch_version": None,
            "torch_cuda_build_version": None,
            "cuda_available": None,
            "torch_gpus": (),
            "diagnostics": (),
        },
    )
    snapshot = profiling.profile_hardware()
    assert snapshot.system_ram_total_bytes > 0
    assert snapshot.system_ram_available_bytes <= snapshot.system_ram_total_bytes
    assert snapshot.process_rss_bytes > 0
    assert snapshot.logical_cpu_count >= 1
