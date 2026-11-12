"""Pins established by checkpoint inspection, not by mutable model metadata."""

from collections.abc import Mapping
import hashlib
from pathlib import Path


class ModelLoadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


ARTIFACT_HASHES = {
    "text": {
        "added_tokens.json": "dc046d04c9b0ada7ae6f1dc89c465801799acdf0c9a6aab8c15a1b2d5ca4e91f",
        "config.json": "a9512ad54a256ca2e26bb16336cfcaa7c93d071a8667c659044003ef3973a9e2",
        "model.safetensors": "c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265",
        "special_tokens_map.json": "9463f61e1b109a8eb4688b829260d7c6b1e6dff04c98ff7269bb89e2b92369b9",
        "spm.model": "c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd",
        "tokenizer.json": "5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964",
        "tokenizer_config.json": "e6c4c771911c211618a2d46488dc7e9e499f051773cd4ff4faeca6fe55fdf569",
    },
    "code": {
        "adapter.safetensors": "be24e173379430877717649c4e1679da5763e272a76f6d1c0783c4e45b07c4fe",
        "adapter_config.json": "d755ae16f601114bb2cec461192150ea54f9f632dd4f108be66f7be3280b3c0c",
        "config.json": "742474d6148a061fa975dadc09ce93725fa9673c55421ed316ef75532cc6b7aa",
        "merges.txt": "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5",
        "pytorch_model.bin": "28b61fd8fa069f6bc966f4cb9572a4026ab2a784fca8fb224020d91b744e32d6",
        "special_tokens_map.json": "7638f5bbbe86ef6d604ef28ad3647dc690d6d117c81c0d63e885416be8da1150",
        "tokenizer_config.json": "994f46754c5bf4014f1aa92d34b1374319c3a6b3f702105cd5b742beaecd18ce",
        "vocab.json": "06b4d46c8e752d410213d9548eb27a54db70fda0319b6271fb8d59dead5e1cab",
    },
}

MODEL_INFO = {
    "text": {
        "model_name": "desklib/ai-text-detector-v1.01",
        "positive_label": "AI-generated text",
        "probability_meaning": "Raw sigmoid score for label 1 (AI); not calibrated confidence.",
        "experimental": False,
        "university_validated": False,
        "warnings": [
            "English-focused detector; short or non-English content needs separate coverage checks.",
            "The original training maximum length is undocumented; inference is capped at 512 tokens.",
            "Student-report accuracy has not been established on the bundled, unlabeled PDFs.",
        ],
    },
    "code": {
        "model_name": "Local CodeBERT + custom LoRA style detector",
        "positive_label": "AI-style synthetic code",
        "probability_meaning": "Raw sigmoid score for synthetic-style label 1, NOT AI-authorship probability.",
        "experimental": True,
        "university_validated": False,
        "validated_languages": ["python", "javascript"],
        "warnings": [
            "Both training labels came from the same synthetic template generator, not authenticated authorship.",
            "Synthetic validation: 78.125% accuracy; 20/80 human-style examples flagged at threshold 0.5.",
            "These metrics do not establish reliability on student code; C/C++ was not validated.",
        ],
    },
}


def verify_artifacts(directory: Path, expected: Mapping[str, str]) -> None:
    """Verify all inference inputs before loading anything; never fetch replacements."""
    if not directory.is_dir():
        raise ModelLoadError("files_missing", "Local model directory is missing.")
    # Prevent HF from selecting an uninspected alternate tokenizer/config file.
    allowed = set(expected) | {"metrics.json", ".DS_Store"}
    unexpected = sorted(p.name for p in directory.iterdir() if p.name not in allowed)
    if unexpected:
        raise ModelLoadError("unverified_artifacts", f"Uninspected model artifact: {unexpected[0]}")
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file():
            raise ModelLoadError("files_missing", f"Required local artifact is missing: {name}")
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != digest:
            raise ModelLoadError("artifact_mismatch", f"Inspected SHA-256 does not match: {name}")
