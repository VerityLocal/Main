"""CPU/CUDA LoRA BGE training with in-batch negatives and duplicate rejection."""

import argparse
import json
import random
from pathlib import Path

from backend.app.core.config import Settings, load_platform_config
from backend.app.services.model_manager import ModelManager
from backend.scripts.dataset_utils import read_records
from backend.scripts.training_runtime import TrainingRuntime, add_runtime_arguments


def main():
    parser = argparse.ArgumentParser(
        description="Train BGE on approved positive query/passage JSONL"
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=1)
    add_runtime_arguments(parser)
    args = parser.parse_args()
    if args.output.exists() or args.batch_size < 2 or args.epochs < 1:
        raise SystemExit("New output and batch size >=2 are required for in-batch negatives")
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from sentence_transformers import SentenceTransformer, losses

    runtime = TrainingRuntime(args.device, args.precision, args.gpu_memory_gib)
    print(json.dumps({"training_execution": runtime.measurements()}))
    random.seed(42)
    torch.manual_seed(42)
    settings = Settings()
    manager = ModelManager(settings, load_platform_config(settings.config_dir))
    model = SentenceTransformer(
        str(manager.path("dense_retriever")), device=str(runtime.device), local_files_only=True
    )
    model.max_seq_length = 512
    runtime.enable_checkpointing(model[0].auto_model, args.checkpointing)
    model[0].auto_model = get_peft_model(
        model[0].auto_model,
        LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION,
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=["query", "value"],
        ),
    )
    loss_function = losses.MultipleNegativesRankingLoss(model)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-5)
    records = [r for r in read_records(args.data) if r["split"] == "train"]
    if len(records) < 2:
        raise ValueError("At least two positive pairs required")
    logs = []
    for epoch in range(args.epochs):
        random.shuffle(records)
        model.train()
        for i in range(0, len(records), args.batch_size):
            batch = records[i : i + args.batch_size]
            if len(batch) < 2:
                continue
            if len({record["passage"] for record in batch}) != len(batch):
                raise ValueError("Duplicate passages create false in-batch negatives")
            queries = [
                "Represent this sentence for searching relevant passages: " + r["query"]
                for r in batch
            ]
            features = [model.tokenize(queries), model.tokenize([r["passage"] for r in batch])]
            features = [
                {key: value.to(runtime.device) for key, value in item.items()} for item in features
            ]
            optimizer.zero_grad(set_to_none=True)
            with runtime.autocast():
                loss = loss_function(features, labels=None)
            runtime.backward(loss)
            runtime.step(optimizer, model.parameters())
            logs.append(
                {"epoch": epoch + 1, "batch_pairs": len(batch), "loss": float(loss.detach())}
            )
    if not runtime.optimizer_steps:
        raise ValueError("No successful optimizer steps; no trained artifact to export")
    execution = runtime.measurements()
    model.cpu().float().eval()
    model[0].auto_model = model[0].auto_model.merge_and_unload(safe_merge=True)
    model.save(str(args.output))
    (args.output / "training_log.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")
    (args.output / "training_execution.json").write_text(
        json.dumps(execution, indent=2), encoding="utf-8"
    )
    print("BGE artifact exported; retrieval/hard-negative evaluation required before deployment.")


if __name__ == "__main__":
    main()
