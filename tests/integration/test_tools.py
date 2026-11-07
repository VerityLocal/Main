"""Every delivered CLI exposes usage without downloads or data processing."""

import subprocess
import sys

import pytest

from backend.app.core.config import PROJECT_ROOT


@pytest.mark.parametrize(
    "module",
    [
        "train_ai_detector",
        "train_bge_retriever",
        "train_nli",
        "verify_cuda_training",
        "verify_detector_deployment",
        "prepare_llmtrace",
        "evaluate",
        "extract_features",
        "export_onnx",
        "download_models",
        "pair_extension",
        "benchmark",
    ],
)
def test_cli_help(module):
    result = subprocess.run(
        [sys.executable, "-m", f"backend.scripts.{module}", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
