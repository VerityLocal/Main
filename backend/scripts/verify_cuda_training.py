"""Measure actual CUDA backward/optimizer steps on the pinned AI architecture."""

import argparse
import json
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from backend.app.core.config import Settings, load_platform_config
from backend.app.runtime.profiling import profile_hardware
from backend.scripts.training_runtime import TrainingRuntime


def main():
    parser = argparse.ArgumentParser(description="Run a synthetic CUDA training smoke check")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--precision", choices=["fp32", "fp16", "bf16"])
    parser.add_argument("--gpu-memory-gib", type=float, default=3.0)
    args = parser.parse_args()
    if args.output.exists() or args.steps < 1:
        raise SystemExit("Use a new report path and a positive step count")
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModel, AutoTokenizer

    from backend.app.engines.ai_detection.classifier import document_forward
    from backend.app.engines.ai_detection.model import Detector
    from backend.app.engines.stylometry.extractor import FeatureExtractor
    from backend.app.engines.stylometry.normalization import fit_normalizer

    runtime = TrainingRuntime("cuda", args.precision, args.gpu_memory_gib)
    torch.manual_seed(42)
    settings = Settings()
    config = load_platform_config(settings.config_dir)
    spec = config.models.models["ai_backbone"]
    path = settings.model_cache / "ai_backbone" / spec.revision
    if not (path / ".download-complete").is_file():
        raise SystemExit(
            "Download the pinned ai_backbone first with backend.scripts.download_models"
        )
    hardware_before = profile_hardware().model_dump(mode="json")
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
    text = "The museum opens at nine in the morning. Visitors can buy tickets at the entrance."
    extracted = FeatureExtractor(tokenizer).extract(text)
    normalizer = fit_normalizer([row["features"] for row in extracted["sentences"]])
    backbone = AutoModel.from_pretrained(path, local_files_only=True)
    runtime.enable_checkpointing(backbone)
    backbone = get_peft_model(
        backbone,
        LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION,
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=[
                name
                for name, _ in backbone.named_modules()
                if name.endswith(("query_proj", "value_proj"))
            ],
        ),
    )
    model = Detector(backbone).to(runtime.device).train()
    trainable = {name: p for name, p in model.named_parameters() if p.requires_grad}
    before = {name: p.detach().cpu().clone() for name, p in trainable.items()}
    optimizer = torch.optim.AdamW(trainable.values(), lr=2e-4)
    losses = []
    step_seconds = []
    for _ in range(args.steps):
        torch.cuda.synchronize()
        started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        with runtime.autocast():
            sentence, document, valid = document_forward(
                model, text, tokenizer, extracted, normalizer, max_windows=1
            )
            if not valid.all() or len(sentence) != 2:
                raise ValueError("Unexpected synthetic fixture sentence coverage")
            # Numeric gradient targets only: these are NOT human/AI authorship annotations.
            loss = torch.nn.functional.cross_entropy(
                sentence, torch.tensor([0, 1], device=runtime.device)
            ) + torch.nn.functional.cross_entropy(
                document[None, :], torch.tensor([1], device=runtime.device)
            )
        runtime.backward(loss)
        runtime.step(optimizer, model.parameters())
        torch.cuda.synchronize()
        step_seconds.append(time.perf_counter() - started)
        losses.append(float(loss.detach()))
    deltas = {
        name: float((p.detach().cpu() - before[name]).abs().max()) for name, p in trainable.items()
    }
    for family in ("lora_", "sentence_head", "document_head"):
        if not any(value > 0 for name, value in deltas.items() if family in name):
            raise ValueError(f"No measured optimizer update in {family}")
    execution = runtime.measurements()
    hardware_after = profile_hardware().model_dump(mode="json")
    model.cpu().float().eval()
    with torch.inference_mode():
        unmerged_sentence, unmerged_document, _ = document_forward(
            model, text, tokenizer, extracted, normalizer, max_windows=1
        )
    model.backbone = model.backbone.merge_and_unload(safe_merge=True)
    with torch.inference_mode():
        sentence, document, _ = document_forward(
            model, text, tokenizer, extracted, normalizer, max_windows=1
        )
    if not torch.isfinite(sentence).all() or not torch.isfinite(document).all():
        raise ValueError("Merged FP32 CPU forward returned non-finite values")
    torch.testing.assert_close(sentence, unmerged_sentence, atol=1e-5, rtol=1e-4)
    torch.testing.assert_close(document, unmerged_document, atol=1e-5, rtol=1e-4)
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kind": "synthetic_training_smoke_not_authorship_training_or_accuracy_benchmark",
        "model_id": spec.model_id,
        "model_revision": spec.revision,
        "execution": execution,
        "hardware_before_model_load": hardware_before,
        "hardware_after_training": hardware_after,
        "resource_versions": {
            name: version(name) for name in ("torch", "transformers", "peft", "numpy", "spacy")
        },
        "batch_documents": 1,
        "token_window_length": 512,
        "nonpadding_tokens": len(tokenizer.encode(text)),
        "sentence_count": len(extracted["sentences"]),
        "max_windows": 1,
        "gradient_checkpointing": "non_reentrant",
        "feature_profile": "light_v1",
        "lora_rank": 8,
        "steps": args.steps,
        "synthetic_losses": losses,
        "step_seconds_including_synchronization": step_seconds,
        "trainable_parameters": sum(p.numel() for p in trainable.values()),
        "changed_trainable_tensors": sum(value > 0 for value in deltas.values()),
        "merged_fp32_cpu_forward_finite": True,
        "merge_max_abs_logit_difference": max(
            float((sentence - unmerged_sentence).abs().max()),
            float((document - unmerged_document).abs().max()),
        ),
        "checkpoint_exported": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
