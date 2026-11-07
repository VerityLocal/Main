"""Exercise real gradients, window/device transfers, and merged CPU roundtrips."""

import pytest

torch = pytest.importorskip("torch")

from backend.scripts.training_runtime import TrainingRuntime  # noqa: E402


@pytest.mark.parametrize(
    "device,precision", [("mps", None), ("cpu", "fp16"), ("cpu", "bf16"), ("cpu", "int8")]
)
def test_invalid_device_or_precision_fails(device, precision):
    with pytest.raises(ValueError):
        TrainingRuntime(device, precision)


def test_unavailable_cuda_fails_without_cpu_fallback(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(ValueError, match="CUDA is unavailable"):
        TrainingRuntime("cuda")


@pytest.mark.parametrize("ceiling", [0, -1, 3.6, float("inf"), float("nan")])
def test_invalid_memory_ceiling_fails_before_initializing_cuda(monkeypatch, ceiling):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "init", lambda: pytest.fail("Must validate before allocation"))
    with pytest.raises(ValueError, match="memory ceiling"):
        TrainingRuntime("cuda", gpu_memory_gib=ceiling)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_loss_cannot_update_parameters(value):
    runtime = TrainingRuntime()
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    with pytest.raises(ValueError, match="Non-finite training loss"):
        runtime.backward(parameter * value)
    assert parameter.grad is None
    assert runtime.optimizer_steps == 0


def test_nonfinite_cpu_gradient_fails_before_optimizer_update():
    runtime = TrainingRuntime()
    parameter = torch.nn.Parameter(torch.tensor(0.0))
    optimizer = torch.optim.SGD([parameter], lr=0.1)
    runtime.backward(parameter.sqrt())  # Finite loss, infinite derivative.
    with pytest.raises(RuntimeError, match="non-finite"):
        runtime.step(optimizer, [parameter])
    assert parameter.item() == 0.0
    assert runtime.optimizer_steps == 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA device and wheel required")
def test_fp16_scaler_skips_overflow_and_recovers():
    runtime = TrainingRuntime("cuda", "fp16")
    parameter = torch.nn.Parameter(torch.tensor(0.0, device=runtime.device))
    optimizer = torch.optim.SGD([parameter], lr=0.1)
    original_scale = runtime.scaler.get_scale()
    runtime.backward(parameter.sqrt())
    runtime.step(optimizer, [parameter])
    assert parameter.item() == 0.0
    assert runtime.optimizer_steps == 0 and runtime.skipped_optimizer_steps == 1
    assert runtime.scaler.get_scale() < original_scale
    optimizer.zero_grad(set_to_none=True)
    runtime.backward((parameter - 1).square())
    runtime.step(optimizer, [parameter])
    assert parameter.item() > 0
    assert runtime.optimizer_steps == 1


@pytest.mark.parametrize("device,precision", [("cpu", "fp32"), ("cuda", "bf16"), ("cuda", "fp16")])
def test_windowed_lora_training_and_merged_cpu_roundtrip(device, precision, tmp_path):
    if device == "cuda":
        if not torch.cuda.is_available():
            pytest.skip("CUDA device and wheel required")
        if precision == "bf16" and not torch.cuda.is_bf16_supported():
            pytest.skip("Native BF16 required")
    pytest.importorskip("peft")
    from peft import LoraConfig, TaskType, get_peft_model
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import AutoModel, DebertaV2Config, PreTrainedTokenizerFast

    from backend.app.engines.ai_detection.classifier import document_forward
    from backend.app.engines.ai_detection.model import Detector
    from backend.app.engines.stylometry.extractor import FeatureExtractor
    from backend.app.engines.stylometry.normalization import fit_normalizer

    torch.manual_seed(42)
    runtime = TrainingRuntime(device, precision)
    core = Tokenizer(
        WordLevel({"[UNK]": 0, "[PAD]": 1, "hello": 2, "world": 3, ".": 4}, unk_token="[UNK]")
    )
    core.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=core, unk_token="[UNK]", pad_token="[PAD]")
    # A sentence crosses overlapping windows, followed by another sentence.
    text = "hello " * 600 + ". world."
    extracted = FeatureExtractor(tokenizer).extract(text)
    normalizer = fit_normalizer([row["features"] for row in extracted["sentences"]])
    config = DebertaV2Config(
        vocab_size=8,
        hidden_size=12,
        num_hidden_layers=1,
        num_attention_heads=3,
        intermediate_size=16,
        max_position_embeddings=512,
        relative_attention=True,
        pos_att_type=["p2c", "c2p"],
        position_buckets=8,
        max_relative_positions=32,
        hidden_dropout_prob=0.0,
        attention_probs_dropout_prob=0.0,
    )
    backbone = AutoModel.from_config(config)
    runtime.enable_checkpointing(backbone, requested=True)
    backbone = get_peft_model(
        backbone,
        LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION,
            r=2,
            lora_alpha=4,
            lora_dropout=0.0,
            target_modules=["query_proj", "value_proj"],
        ),
    )
    model = Detector(backbone, fusion_dim=4).to(runtime.device).train()
    before = {name: p.detach().cpu().clone() for name, p in model.named_parameters()}
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=0.01)
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        with runtime.autocast():
            sentence, document, valid = document_forward(
                model, text, tokenizer, extracted, normalizer, max_windows=2
            )
            assert all(value.device.type == device for value in (sentence, document, valid))
            assert valid.tolist() == [True, True]
            loss = torch.nn.functional.cross_entropy(
                sentence, torch.tensor([0, 1], device=runtime.device)
            ) + torch.nn.functional.cross_entropy(
                document[None, :], torch.tensor([1], device=runtime.device)
            )
        runtime.backward(loss)
        runtime.step(optimizer, model.parameters())
    measurements = runtime.measurements()
    assert measurements["optimizer_steps"] > 0
    assert measurements["optimizer_steps"] + measurements["skipped_optimizer_steps"] == 3
    if device == "cuda":
        assert 0 < measurements["peak_allocated_bytes"] < measurements["memory_ceiling_bytes"]
    changed = set()
    for name, parameter in model.named_parameters():
        if not torch.equal(parameter.detach().cpu(), before[name]):
            assert parameter.requires_grad, "The frozen backbone must not be updated"
            changed.add(name)
    for family in ("lora_", "sentence_head", "document_head"):
        assert any(family in name for name in changed)
    model.cpu().float().eval()
    with torch.inference_mode():
        expected = document_forward(model, text, tokenizer, extracted, normalizer, max_windows=2)
    model.backbone = model.backbone.merge_and_unload(safe_merge=True)
    assert all(p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters())
    torch.save(model.state_dict(), tmp_path / "weights.pt")
    restored = Detector(AutoModel.from_config(config), fusion_dim=4).eval()
    restored.load_state_dict(torch.load(tmp_path / "weights.pt", weights_only=True))
    with torch.inference_mode():
        actual = document_forward(restored, text, tokenizer, extracted, normalizer, max_windows=2)
    for result, reference in zip(actual, expected, strict=True):
        torch.testing.assert_close(result, reference, rtol=1e-4, atol=1e-5)
    with torch.inference_mode(), pytest.raises(ValueError, match="window budget"):
        document_forward(restored, text, tokenizer, extracted, normalizer, max_windows=1)
