"""Held-out evaluation with one FP32 CPU checkpoint load and raw-logit calibration."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from backend.app.core.config import Settings, load_platform_config
from backend.app.engines.ai_detection.artifact import validate_manifest
from backend.app.engines.ai_detection.inference import checkpoint_extractor, load_detector_weights
from backend.app.runtime.calibration import fit_temperature
from backend.app.runtime.metrics import binary_metrics, classification_summary
from backend.app.services.model_manager import ModelManager
from backend.scripts.dataset_utils import (
    dataset_provenance,
    file_sha256,
    read_records,
    split_identities,
)


def collect_logits(records, checkpoint, manifest, models):
    import torch
    from transformers import AutoTokenizer

    from backend.app.engines.ai_detection.classifier import document_forward

    validate_manifest(manifest, models.config)
    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint / "tokenizer", local_files_only=True, use_fast=True
    )
    extractor = checkpoint_extractor(manifest, models, tokenizer)
    prepared = []
    for row in records:
        profile = manifest.get("input_profile")
        if profile and len(tokenizer.encode(row["text"], truncation=False)) > profile["max_tokens"]:
            raise ValueError("Evaluation input exceeds the checkpoint's trained input profile")
        extracted = extractor.extract(row["text"], row.get("language", "en"))
        spans = {(s["start_offset"], s["end_offset"]) for s in extracted["sentences"]}
        annotations = {}
        for item in row.get("sentence_labels", []):
            key = item["start_offset"], item["end_offset"]
            if key not in spans or type(item["label"]) is not int or item["label"] not in {0, 1}:
                raise ValueError("Evaluation sentence labels must match original UTF-16 spans")
            if key in annotations:
                raise ValueError("Duplicate evaluation sentence annotation")
            annotations[key] = item["label"]
        prepared.append((extracted, annotations))
    models.unload()
    model = load_detector_weights(checkpoint, manifest)
    document_logits, sentence_logits, sentence_labels = [], [], []
    with torch.inference_mode():
        for i, (row, (extracted, annotations)) in enumerate(zip(records, prepared, strict=True), 1):
            sentence, document, valid = document_forward(
                model, row["text"], tokenizer, extracted, manifest["normalizer"]
            )
            if not torch.isfinite(sentence).all() or not torch.isfinite(document).all():
                raise ValueError("Non-finite deployment logits")
            document_logits.append(document.tolist())
            for j, span in enumerate(extracted["sentences"]):
                key = span["start_offset"], span["end_offset"]
                if valid[j] and key in annotations:
                    sentence_logits.append(sentence[j].tolist())
                    sentence_labels.append(annotations[key])
            if i % 128 == 0 or i == len(records):
                print(
                    json.dumps(
                        {"stage": "fp32_cpu_evaluation", "documents": i, "total": len(records)}
                    ),
                    flush=True,
                )
    return document_logits, sentence_logits, sentence_labels


def probabilities(logits, temperature):
    import torch

    return (torch.tensor(logits, dtype=torch.float32) / temperature).softmax(-1)[:, 1].tolist()


def available_metrics(labels, scores):
    return (
        binary_metrics(labels, scores)
        if set(labels) == {0, 1}
        else classification_summary(labels, scores)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--split", choices=["validation", "calibration", "final_test"], required=True
    )
    parser.add_argument("--fit-calibration", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Evaluation output must be new")
    if args.fit_calibration and args.split != "calibration":
        raise SystemExit("Only the held-out calibration split may fit temperatures")
    started = time.perf_counter()
    settings = Settings(detector_checkpoint=args.checkpoint)
    models = ModelManager(settings, load_platform_config(settings.config_dir))
    all_records = read_records(args.data)
    provenance = dataset_provenance(args.data, all_records)
    records = [row for row in all_records if row["split"] == args.split]
    labels = [row["label"] for row in records]
    if not labels or set(labels) != {0, 1} or any(type(label) is not int for label in labels):
        raise ValueError("Evaluation requires labeled examples of both document classes")
    manifest_path = args.checkpoint / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if provenance["document_label_policy"] != manifest.get(
        "document_label_policy", "binary_authorship_v1"
    ):
        raise ValueError("Evaluation and checkpoint document-label policies differ")
    if args.fit_calibration and manifest.get("calibration"):
        raise SystemExit("Checkpoint is already calibrated; do not refit silently")
    selected_identities = set(split_identities(records).get(args.split, []))
    seen = manifest.get("seen_split_identities", {})
    if not seen:
        raise SystemExit("Artifact lacks leakage identities; cannot certify a held-out evaluation")
    if any(selected_identities & set(keys) for split, keys in seen.items() if split != args.split):
        raise SystemExit("Evaluation overlaps checkpoint training/selection/calibration groups")
    doc_logits, sent_logits, sent_labels = collect_logits(
        records, args.checkpoint, manifest, models
    )
    calibration = manifest.get("calibration") or {}
    report = {
        "split": args.split,
        "document_label_policy": provenance["document_label_policy"],
        "data_sha256": provenance["data_sha256"],
        "weights_sha256": file_sha256(args.checkpoint / "weights.pt"),
        "execution": {"device": "cpu", "precision": "fp32", "checkpoint_loads": 1},
    }
    if args.fit_calibration:
        calibration = {
            "document_temperature": fit_temperature(doc_logits, labels),
            "sentence_temperature": fit_temperature(sent_logits, sent_labels),
            "artifact_id": uuid4().hex,
            "split": "calibration",
            "precision": "fp32_cpu",
            "input_profile": manifest.get("input_profile"),
        }
        report["before_calibration"] = {
            **binary_metrics(labels, probabilities(doc_logits, 1)),
            "sentence_metrics": binary_metrics(sent_labels, probabilities(sent_logits, 1)),
        }
        report["fitted_calibration"] = calibration
        report["metrics_scope"] = "fit_split_diagnostics_not_held_out_performance"
    doc_scores = probabilities(doc_logits, calibration.get("document_temperature", 1))
    sent_scores = (
        probabilities(sent_logits, calibration.get("sentence_temperature", 1))
        if sent_logits
        else []
    )
    report.update(
        **binary_metrics(labels, doc_scores),
        calibrated=bool(calibration),
        sentence_metrics=available_metrics(sent_labels, sent_scores) if sent_labels else None,
    )
    report["strata"] = {}
    for key in ("domain", "generator", "mixed_document", "source_label"):
        report["strata"][key] = {}
        for value in sorted({str(row[key]) for row in records if key in row}):
            selected = [i for i, row in enumerate(records) if str(row.get(key)) == value]
            report["strata"][key][value] = available_metrics(
                [labels[i] for i in selected], [doc_scores[i] for i in selected]
            )
    report["elapsed_seconds"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    if args.fit_calibration:
        manifest["calibration"] = calibration
        manifest["seen_split_identities"]["calibration"] = sorted(selected_identities)
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(manifest_path)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "macro_f1": report["macro_f1"],
                "roc_auc": report["roc_auc"],
                "calibrated": bool(calibration),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
