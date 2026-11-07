"""CPU/CUDA LoRA with real labels, overlap aggregation, and FP32 CPU export."""

import argparse
import json
import math
import random
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from backend.app.core.config import Settings, load_platform_config
from backend.app.document.chunking import sentence_spans
from backend.app.engines.stylometry.extractor import SCHEMA, FeatureExtractor
from backend.app.engines.stylometry.normalization import fit_normalizer
from backend.app.engines.stylometry.reference_lm import ReferenceScorer
from backend.app.services.model_manager import ModelManager
from backend.scripts.dataset_utils import dataset_provenance, read_records, split_identities
from backend.scripts.training_runtime import TrainingRuntime, add_runtime_arguments


def main():
    parser = argparse.ArgumentParser(
        description="Train the CPU/CUDA LoRA AI baseline; real labeled JSONL required"
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--accumulation", type=int, default=1)
    parser.add_argument("--fusion-dim", type=int, default=128)
    parser.add_argument("--max-windows", type=int, help="Default: 4 on CPU, 1 on CUDA")
    parser.add_argument("--profile", choices=["light_v1", "full_v1"], default="light_v1")
    add_runtime_arguments(parser)
    parser.add_argument("--lambda-doc", type=float, default=1)
    parser.add_argument("--lambda-sent", type=float, default=1)
    parser.add_argument("--log-every", type=int, default=128, help="Progress every N documents")
    args = parser.parse_args()
    if args.max_windows is None:
        args.max_windows = 1 if args.device == "cuda" else 4
    if any(not math.isfinite(value) or value <= 0 for value in (args.lambda_doc, args.lambda_sent)):
        raise SystemExit("This two-head baseline needs positive document and sentence loss weights")
    if (
        args.output.exists()
        or min(args.epochs, args.accumulation, args.fusion_dim, args.max_windows, args.log_every)
        < 1
    ):
        raise SystemExit("Output must be new and training sizes positive")
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModel, AutoTokenizer

    from backend.app.engines.ai_detection.classifier import document_forward
    from backend.app.engines.ai_detection.model import Detector

    runtime = TrainingRuntime(args.device, args.precision, args.gpu_memory_gib)
    print(json.dumps({"training_execution": runtime.measurements()}))
    random.seed(42)
    torch.manual_seed(42)
    settings = Settings()
    config = load_platform_config(settings.config_dir)
    manager = ModelManager(settings, config)
    path = manager.path("ai_backbone")
    if not (path / ".download-complete").is_file():
        raise SystemExit("Download the pinned ai_backbone first")
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
    uses_pos = manager.available("pos_tagger")

    def pos(text):
        with manager.lease("pos_tagger") as bundle:
            return [[token.pos_ for token in sentence] for sentence in bundle.model(text).sents]

    extractor = FeatureExtractor(
        tokenizer,
        profile=args.profile,
        pos=pos if uses_pos else None,
        reference=ReferenceScorer(manager) if args.profile == "full_v1" else None,
    )
    records = read_records(args.data)
    provenance = dataset_provenance(args.data, records)
    train = [record for record in records if record["split"] == "train"]
    validation = [record for record in records if record["split"] == "validation"]
    if not train or not validation or set(record.get("label") for record in train) != {0, 1}:
        raise SystemExit("Need separate train/validation records and both real document classes")
    prepared = {}
    for prepared_count, record in enumerate(train + validation, 1):
        if type(record.get("label")) is not int or record["label"] not in {0, 1}:
            raise ValueError("Document label must be 0 human or 1 AI")
        text = record["text"]
        if len(text) > 20_000:
            raise ValueError("Training document exceeds current profile")
        spans = sentence_spans(text)
        annotated = {
            (item["start_offset"], item["end_offset"]): item["label"]
            for item in record.get("sentence_labels", [])
        }
        if any(key not in {(s.start_offset, s.end_offset) for s in spans} for key in annotated):
            raise ValueError("Sentence annotations must match original UTF-16 sentence spans")
        labels = [annotated.get((s.start_offset, s.end_offset), -100) for s in spans]
        if any(label not in {-100, 0, 1} for label in labels):
            raise ValueError("Invalid sentence label")
        prepared[record["id"]] = (extractor.extract(text, record.get("language", "en")), labels)
        if prepared_count % 1000 == 0:
            print(
                json.dumps({"stage": "feature_preparation", "documents": prepared_count}),
                flush=True,
            )
    sentence_counts = Counter(
        label for r in train for label in prepared[r["id"]][1] if label != -100
    )
    if set(sentence_counts) != {0, 1}:
        raise SystemExit(
            "Both sentence classes need real labels; never export a random sentence head"
        )
    sentence_class_weights = torch.tensor(
        [sum(sentence_counts.values()) / (2 * sentence_counts[i]) for i in range(2)],
        device=runtime.device,
    )
    normalizer = fit_normalizer(
        [row["features"] for record in train for row in prepared[record["id"]][0]["sentences"]]
    )
    manager.unload()
    backbone = AutoModel.from_pretrained(path, local_files_only=True)
    runtime.enable_checkpointing(backbone, args.checkpointing)
    targets = [
        name for name, _ in backbone.named_modules() if name.endswith(("query_proj", "value_proj"))
    ]
    if not targets:
        raise ValueError("Inspect backbone LoRA target modules; expected projections unavailable")
    backbone = get_peft_model(
        backbone,
        LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION,
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=targets,
        ),
    )
    model = Detector(backbone, fusion_dim=args.fusion_dim).to(runtime.device)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-4)
    counts = Counter(record["label"] for record in train)
    class_weights = torch.tensor(
        [len(train) / (2 * counts[i]) for i in range(2)], device=runtime.device
    )
    logs = []
    best_loss, best_epoch = math.inf, None
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    for epoch in range(args.epochs):
        random.shuffle(train)
        model.train()
        losses = []
        for first in range(0, len(train), args.accumulation):
            group = train[first : first + args.accumulation]
            optimizer.zero_grad(set_to_none=True)
            for record in group:
                extracted, labels = prepared[record["id"]]
                with runtime.autocast():
                    sentence_logits, document_logits, valid = document_forward(
                        model,
                        record["text"],
                        tokenizer,
                        extracted,
                        normalizer,
                        max_windows=args.max_windows,
                    )
                    loss = args.lambda_doc * torch.nn.functional.cross_entropy(
                        document_logits[None, :],
                        torch.tensor([record["label"]], device=runtime.device),
                        weight=class_weights,
                        reduction="sum",
                    )
                    sentence_targets = torch.tensor(labels, device=runtime.device)
                    selected = valid & (sentence_targets != -100)
                    if selected.any():
                        loss += args.lambda_sent * torch.nn.functional.cross_entropy(
                            sentence_logits[selected],
                            sentence_targets[selected],
                            weight=sentence_class_weights,
                        )
                losses.append(float(loss.detach()))
                runtime.backward(loss / len(group))
            runtime.step(optimizer, model.parameters())
            completed = first + len(group)
            if completed % args.log_every < len(group) or completed == len(train):
                progress = {
                    "epoch": epoch + 1,
                    "documents": completed,
                    "epoch_documents": len(train),
                    "mean_training_loss": sum(losses) / len(losses),
                    "elapsed_seconds": time.perf_counter() - started,
                    **runtime.measurements(),
                }
                print(json.dumps(progress), flush=True)
                with (args.output / "progress.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(progress, allow_nan=False) + "\n")
        model.eval()
        correct, validation_losses = 0, []
        sentence_correct = sentence_total = 0
        with torch.inference_mode(), runtime.autocast():
            for record in validation:
                extracted, labels = prepared[record["id"]]
                sentence, document, valid = document_forward(
                    model,
                    record["text"],
                    tokenizer,
                    extracted,
                    normalizer,
                    max_windows=args.max_windows,
                )
                correct += int(document.argmax()) == record["label"]
                loss = args.lambda_doc * torch.nn.functional.cross_entropy(
                    document[None, :], torch.tensor([record["label"]], device=runtime.device)
                )
                targets = torch.tensor(labels, device=runtime.device)
                selected = valid & (targets != -100)
                if selected.any():
                    loss += args.lambda_sent * torch.nn.functional.cross_entropy(
                        sentence[selected], targets[selected]
                    )
                    sentence_correct += int(
                        (sentence[selected].argmax(-1) == targets[selected]).sum()
                    )
                    sentence_total += int(selected.sum())
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite validation loss; no checkpoint will be exported")
                validation_losses.append(float(loss))
        logs.append(
            {
                "epoch": epoch + 1,
                "train_loss": sum(losses) / len(losses),
                "validation_accuracy": correct / len(validation),
                "validation_loss": sum(validation_losses) / len(validation_losses),
                "validation_sentence_accuracy": sentence_correct / sentence_total
                if sentence_total
                else None,
            }
        )
        if logs[-1]["validation_loss"] < best_loss:
            best_loss, best_epoch = logs[-1]["validation_loss"], epoch + 1
            torch.save(
                {
                    name: p.detach().cpu().clone()
                    for name, p in model.named_parameters()
                    if p.requires_grad
                },
                args.output / "best_trainable.pt",
            )
        (args.output / "training_log.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")
        print(json.dumps(logs[-1] | {"best_epoch": best_epoch}), flush=True)
    if not runtime.optimizer_steps:
        raise ValueError("No successful optimizer steps; no trained artifact to export")
    execution = runtime.measurements()
    execution["elapsed_seconds"] = time.perf_counter() - started
    best = torch.load(args.output / "best_trainable.pt", map_location="cpu", weights_only=True)
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                parameter.copy_(best[name])
    model.cpu().float().eval()
    model.backbone = model.backbone.merge_and_unload(safe_merge=True)
    tokenizer.save_pretrained(args.output / "tokenizer")
    model.backbone.config.save_pretrained(args.output / "backbone_config")
    torch.save(model.state_dict(), args.output / "weights.pt")
    manifest = {
        "schema": SCHEMA,
        "profile": args.profile,
        "uses_pos": uses_pos,
        "labels": ["human", "ai"],
        "document_label_policy": provenance["document_label_policy"],
        "dataset_provenance": provenance,
        "input_profile": provenance.get("import_manifest", {}).get("profile"),
        "fusion_dim": args.fusion_dim,
        "normalizer": normalizer,
        "deployment_precision": "fp32_cpu",
        "training_execution": execution,
        "model_revisions": {key: spec.revision for key, spec in config.models.models.items()},
        "resource_versions": {
            key: version(key) for key in ["regex", "spacy", "transformers", "torch"]
        },
        "calibration": None,
        "seen_split_identities": split_identities(train + validation),
        "seed": 42,
        "selected_epoch": best_epoch,
        "selection_metric": "minimum_validation_combined_document_sentence_cross_entropy",
        "training_config": vars(args) | {"data": str(args.data), "output": str(args.output)},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.output / "training_log.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")
    print(
        "Merged FP32 CPU checkpoint exported. "
        "Calibrate on a separate split before claiming confidence."
    )


if __name__ == "__main__":
    main()
