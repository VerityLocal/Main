"""Reconstruct the inspected custom heads; strictly load local weights only."""

import json
from typing import Any

from backend.config import Settings
from backend.detectors.artifacts import ARTIFACT_HASHES, ModelLoadError, verify_artifacts
from backend.detectors.inference import LoadedDetector, masked_mean


def build_classifier(backbone: Any, backbone_name: str, head_name: str) -> Any:
    import torch.nn as nn

    class MeanPoolClassifier(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.add_module(backbone_name, backbone)
            self.add_module(head_name, nn.Linear(backbone.config.hidden_size, 1))

        def forward(self, input_ids: Any, attention_mask: Any, **kwargs: Any) -> Any:
            hidden = getattr(self, backbone_name)(
                input_ids=input_ids, attention_mask=attention_mask, **kwargs,
            ).last_hidden_state
            return getattr(self, head_name)(masked_mean(hidden, attention_mask))

    return MeanPoolClassifier()


def merge_code_adapter(backbone: Any, adapter: dict, rank: int, alpha: int) -> dict:
    """Validate the full custom adapter, then merge W += (alpha/r) * B @ A."""
    import torch

    expected = {
        "head.weight": (1, backbone.config.hidden_size),
        "head.bias": (1,),
    }
    projections = []
    for i, layer in enumerate(backbone.encoder.layer):
        for target in ("query", "value"):
            prefix = f"lora.encoder.layer.{i}.attention.self.{target}"
            projection = getattr(layer.attention.self, target)
            out_size, in_size = projection.weight.shape
            expected[prefix + ".A"] = (rank, in_size)
            expected[prefix + ".B"] = (out_size, rank)
            projections.append((projection, prefix))
    if rank <= 0 or alpha <= 0 or set(adapter) != set(expected):
        raise ModelLoadError("invalid_checkpoint", "Code adapter tensor keys or LoRA parameters are invalid.")
    for key, shape in expected.items():
        tensor = adapter[key]
        if tuple(tensor.shape) != shape or not tensor.is_floating_point() or not torch.isfinite(tensor).all():
            raise ModelLoadError("invalid_checkpoint", f"Invalid code adapter tensor: {key}")
    with torch.no_grad():
        for projection, prefix in projections:
            projection.weight.add_(adapter[prefix + ".B"] @ adapter[prefix + ".A"], alpha=alpha / rank)
    return {"weight": adapter["head.weight"], "bias": adapter["head.bias"]}


def load_detector(kind: str, settings: Settings) -> LoadedDetector:
    if kind not in ARTIFACT_HASHES:
        raise ValueError(f"Unknown detector kind: {kind}")
    directory = settings.models_dir / f"{kind}_detector"
    verify_artifacts(directory, ARTIFACT_HASHES[kind])

    # Imports and all heavy allocation happen at startup, not when importing the app.
    import torch
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, DebertaV2Config, DebertaV2Model, RobertaConfig, RobertaModel

    torch.set_num_threads(settings.torch_threads)
    if settings.device == "cuda" and not torch.cuda.is_available():
        raise ModelLoadError("device_unavailable", "CUDA was requested but is unavailable; choose cpu.")
    if settings.device == "mps" and not torch.backends.mps.is_available():
        raise ModelLoadError("device_unavailable", "MPS was requested but is unavailable; choose cpu.")

    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    tokenizer = AutoTokenizer.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False, use_fast=True,
    )
    if kind == "text":
        backbone = DebertaV2Model(DebertaV2Config.from_dict(config))
        model = build_classifier(backbone, "model", "classifier")
        state = load_file(str(directory / "model.safetensors"), device="cpu")
        model.load_state_dict(state, strict=True)
        del state
    else:
        metadata = json.loads((directory / "adapter_config.json").read_text(encoding="utf-8"))
        if (metadata["r"], metadata["alpha"], metadata["targets"], metadata["head"]) != (
            16, 32, ["query", "value"], "mean-pooled linear",
        ):
            raise ModelLoadError("invalid_checkpoint", "Code adapter architecture is not the inspected one.")
        backbone = RobertaModel(RobertaConfig.from_dict(config))
        # Never allow arbitrary pickle objects from .bin files.
        state = torch.load(directory / "pytorch_model.bin", map_location="cpu", weights_only=True)
        backbone.load_state_dict(state, strict=True)
        del state
        adapter = load_file(str(directory / "adapter.safetensors"), device="cpu")
        head_state = merge_code_adapter(backbone, adapter, metadata["r"], metadata["alpha"])
        model = build_classifier(backbone, "backbone", "head")
        model.head.load_state_dict(head_state, strict=True)
        del adapter, head_state
    model.to(settings.device)
    model.eval()
    return LoadedDetector(kind, tokenizer, model, settings.device, settings.max_tokens, settings.batch_size)
