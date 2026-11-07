"""CPU/CUDA LoRA NLI fine-tuning with inspected labels and real annotations."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import Settings, load_platform_config
from backend.app.services.model_manager import ModelManager
from backend.scripts.dataset_utils import read_records
from backend.scripts.training_runtime import TrainingRuntime, add_runtime_arguments


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune the pinned NLI model from labeled premise/hypothesis pairs"
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=1)
    add_runtime_arguments(parser)
    args = parser.parse_args()
    if args.output.exists() or args.epochs < 1:
        raise SystemExit("New output and positive epoch count required")
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    runtime = TrainingRuntime(args.device, args.precision, args.gpu_memory_gib)
    print(json.dumps({"training_execution": runtime.measurements()}))
    torch.manual_seed(42)
    settings = Settings()
    manager = ModelManager(settings, load_platform_config(settings.config_dir))
    path = manager.path("nli_verifier")
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    base = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True)
    labels = base.config.label2id
    if set(labels) != {"entailment", "contradiction", "neutral"}:
        raise ValueError("NLI label mapping is not verified")
    runtime.enable_checkpointing(base, args.checkpointing)
    model = get_peft_model(
        base,
        LoraConfig(
            task_type=TaskType.SEQ_CLS,
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=["query_proj", "value_proj"],
        ),
    ).to(runtime.device)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-5)
    records = [r for r in read_records(args.data) if r["split"] == "train"]
    if not records or any(r.get("label") not in labels for r in records):
        raise ValueError("Real three-class NLI annotations are required")
    model.train()
    for _epoch in range(args.epochs):
        for record in records:
            inputs = tokenizer(
                record["premise"],
                record["hypothesis"],
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(runtime.device)
            optimizer.zero_grad(set_to_none=True)
            with runtime.autocast():
                output = model(
                    **inputs, labels=torch.tensor([labels[record["label"]]], device=runtime.device)
                )
            runtime.backward(output.loss)
            runtime.step(optimizer, model.parameters())
    if not runtime.optimizer_steps:
        raise ValueError("No successful optimizer steps; no trained artifact to export")
    execution = runtime.measurements()
    model.cpu().float().eval().merge_and_unload(safe_merge=True).save_pretrained(
        args.output, safe_serialization=True
    )
    tokenizer.save_pretrained(args.output)
    (args.output / "training_execution.json").write_text(
        json.dumps(execution, indent=2), encoding="utf-8"
    )
    print(
        "NLI artifact exported; calibration, temporal/source evaluation "
        "and registration remain required."
    )


if __name__ == "__main__":
    main()
