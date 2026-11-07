"""Fail-closed compatibility for feature resources and deployment calibration."""

import math
from importlib.metadata import version

from backend.app.engines.stylometry.extractor import SCHEMA


def validate_manifest(manifest, config):
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("labels") != ["human", "ai"]
        or manifest.get("deployment_precision") != "fp32_cpu"
        or manifest.get("profile") not in {"light_v1", "full_v1"}
    ):
        raise ValueError("Detector artifact contract or deployment mismatch")
    if manifest.get("document_label_policy", "binary_authorship_v1") not in {
        "binary_authorship_v1",
        "contains_annotated_ai_v1",
    }:
        raise ValueError("Unsupported detector document-label policy")
    input_profile = manifest.get("input_profile")
    if input_profile is not None and (
        not isinstance(input_profile, dict)
        or type(input_profile.get("max_tokens")) is not int
        or not 2 <= input_profile["max_tokens"] <= 512
    ):
        raise ValueError("Invalid detector input profile")
    required = {"ai_backbone"}
    if manifest.get("uses_pos"):
        required.add("pos_tagger")
    if manifest["profile"] == "full_v1":
        required.add("reference_lm")
    for name in required:
        if manifest.get("model_revisions", {}).get(name) != config.models.models[name].revision:
            raise ValueError("Detector feature/backbone model revision mismatch")
    for name in ("regex", "spacy", "transformers", "torch"):
        if manifest.get("resource_versions", {}).get(name) != version(name):
            raise ValueError("Detector feature resource version mismatch")
    normalizer = manifest.get("normalizer", {})
    if any(len(normalizer.get(key, [])) != 24 for key in ("means", "scales", "valid_counts")):
        raise ValueError("Detector normalizer must contain exactly 24 columns")
    if (
        not all(math.isfinite(x) for x in normalizer["means"])
        or not all(math.isfinite(x) and x > 0 for x in normalizer["scales"])
        or not all(type(x) is int and x >= 0 for x in normalizer["valid_counts"])
    ):
        raise ValueError("Invalid detector normalization statistics")
    calibration = manifest.get("calibration")
    if calibration:
        if (
            calibration.get("split") != "calibration"
            or calibration.get("precision") != "fp32_cpu"
            or not calibration.get("artifact_id")
        ):
            raise ValueError("Calibration artifact deployment mismatch")
        for key in ("sentence_temperature", "document_temperature"):
            value = calibration.get(key)
            if not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid calibration temperature")
