"""Load a validated local trained artifact; otherwise return explicit unavailability."""

import json


def checkpoint_extractor(manifest, models, tokenizer):
    from backend.app.engines.stylometry.extractor import FeatureExtractor
    from backend.app.engines.stylometry.reference_lm import ReferenceScorer

    pos = None
    if manifest.get("uses_pos"):
        if not models.available("pos_tagger"):
            raise ValueError("Detector requires its trained POS profile")

        def pos(text):
            with models.lease("pos_tagger") as bundle:
                return [[token.pos_ for token in sentence] for sentence in bundle.model(text).sents]

    profile = manifest["profile"]
    if profile == "full_v1" and not models.available("reference_lm"):
        raise ValueError("Detector requires its trained reference-LM profile")
    return FeatureExtractor(
        tokenizer,
        profile=profile,
        pos=pos,
        reference=ReferenceScorer(models) if profile == "full_v1" else None,
    )


def load_detector_weights(checkpoint, manifest):
    import torch
    from transformers import AutoConfig, AutoModel

    from backend.app.engines.ai_detection.model import Detector

    config = AutoConfig.from_pretrained(checkpoint / "backbone_config", local_files_only=True)
    model = Detector(AutoModel.from_config(config), fusion_dim=manifest["fusion_dim"])
    state = torch.load(checkpoint / "weights.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    return model.cpu().float().eval()


def analyze(document, models, settings, context):
    checkpoint = settings.detector_checkpoint
    if checkpoint is None or not (checkpoint / "manifest.json").is_file():
        return {
            "status": "unavailable",
            "findings": [],
            "reason": (
                "No trained AI detector checkpoint. Train and calibrate using labeled data; "
                "base DeBERTa is not a detector."
            ),
        }
    import torch
    from transformers import AutoTokenizer

    from backend.app.engines.ai_detection.artifact import validate_manifest
    from backend.app.engines.ai_detection.classifier import document_forward
    from backend.app.schemas.finding import Finding

    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(manifest, models.config)
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint / "tokenizer", local_files_only=True, use_fast=True
    )
    profile = manifest["profile"]
    input_profile = manifest.get("input_profile")
    if (
        input_profile
        and len(tokenizer.encode(document.extracted_text, truncation=False))
        > input_profile["max_tokens"]
    ):
        return {
            "status": "unavailable",
            "findings": [],
            "reason": (
                f"This pilot detector supports at most {input_profile['max_tokens']} "
                "tokens per document."
            ),
            "diagnostics": {"outside_trained_input_profile": True, "input_profile": input_profile},
        }
    extracted = checkpoint_extractor(manifest, models, tokenizer).extract(
        document.extracted_text, document.language
    )
    if not extracted["sentences"]:
        return {"status": "unavailable", "findings": [], "reason": "No sentence candidates"}
    models.unload()
    model = load_detector_weights(checkpoint, manifest)
    with torch.inference_mode():
        sentence_logits, document_logits, valid = document_forward(
            model,
            document.extracted_text,
            tokenizer,
            extracted,
            manifest["normalizer"],
            context.check,
        )
    calibration = manifest.get("calibration")
    sentence_temperature = calibration["sentence_temperature"] if calibration else 1
    document_temperature = calibration["document_temperature"] if calibration else 1
    scores = (sentence_logits / sentence_temperature).softmax(-1)[:, 1].tolist()
    findings = []
    for i, (row, score) in enumerate(zip(extracted["sentences"], scores, strict=True)):
        if not valid[i]:
            continue
        finding = Finding(
            **{
                "finding_id": f"ai_{i}",
                "document_id": document.document_id,
                "revision": document.revision,
                "offset_unit": "utf16_code_unit",
                "start_offset": row["start_offset"],
                "end_offset": row["end_offset"],
                "category": "AI_GENERATED_CANDIDATE",
                "score": score,
                "confidence": score if calibration else None,
                "confidence_interpretation": (
                    "probability_calibrated" if calibration else "not_available"
                ),
                "calibration_artifact_id": calibration["artifact_id"] if calibration else None,
                "diagnostics": {
                    "calibrated": bool(calibration),
                    "not_authorship_proof": True,
                    "calibration_artifact_id": calibration["artifact_id"] if calibration else None,
                    "score_interpretation": "estimated_p_ai_not_proof_of_authorship",
                },
            }
        )
        finding.validate_against(document)
        findings.append(finding.model_dump(mode="json"))
    return {
        "status": "completed",
        "findings": findings,
        "document_score": float((document_logits / document_temperature).softmax(-1)[1]),
        "diagnostics": {
            "calibrated": bool(calibration),
            "profile": profile,
            "device": "cpu",
            "document_label_policy": manifest.get("document_label_policy", "binary_authorship_v1"),
            "document_score_interpretation": (
                "estimated_probability_contains_annotated_ai"
                if manifest.get("document_label_policy") == "contains_annotated_ai_v1"
                else "estimated_probability_ai_authorship"
            ),
            "input_profile": input_profile,
        },
    }
