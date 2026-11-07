"""Tiny synthetic neural fixtures, not pretrained/trained model validation."""

import json
import time
from contextlib import contextmanager
from importlib.metadata import version
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from backend.app.core.config import load_platform_config  # noqa: E402
from backend.app.document.builder import build_document  # noqa: E402
from backend.app.engines.ai_detection.artifact import validate_manifest  # noqa: E402
from backend.app.engines.ai_detection.inference import analyze  # noqa: E402
from backend.app.engines.ai_detection.model import Detector  # noqa: E402
from backend.app.engines.ai_detection.pooling import sentence_pool  # noqa: E402
from backend.app.engines.plagiarism.dense_retrieval import DenseRetriever  # noqa: E402
from backend.app.runtime.calibration import fit_temperature  # noqa: E402
from backend.app.runtime.inference_queue import AnalysisContext  # noqa: E402
from backend.app.services.model_manager import ModelBundle, ModelManager  # noqa: E402


def test_pooling_masks_padding_and_empty_sentences():
    hidden = torch.tensor([[[1.0, 2.0], [3.0, 4.0], [100.0, 100.0]]])
    spans = torch.tensor([[[True, True, True], [False, False, False]]])
    pooled, valid = sentence_pool(hidden, spans, torch.tensor([[1, 1, 0]]))
    assert pooled.tolist() == [[[2.0, 3.0, 3.0, 4.0], [0.0, 0.0, 0.0, 0.0]]]
    assert valid.tolist() == [[True, False]]


def test_tiny_artifact_shared_forward_and_compatibility(tmp_path, settings_factory):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import AutoModel, DebertaV2Config, PreTrainedTokenizerFast

    settings = settings_factory(detector_checkpoint=tmp_path / "checkpoint")
    checkpoint = settings.detector_checkpoint
    checkpoint.mkdir()
    config = load_platform_config(settings.config_dir)
    tokenizer_core = Tokenizer(
        WordLevel({"[UNK]": 0, "[PAD]": 1, "hello": 2, ".": 3}, unk_token="[UNK]")
    )
    tokenizer_core.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer_core, unk_token="[UNK]", pad_token="[PAD]"
    )
    from backend.app.engines.ai_detection.windows import window_batches
    from backend.app.engines.stylometry.extractor import FeatureExtractor

    long_text = "hello " * 600 + "."
    extracted = FeatureExtractor(tokenizer).extract(long_text)
    normalizer = {"means": [0.0] * 24, "scales": [1.0] * 24, "valid_counts": [10] * 24}
    batches = list(window_batches(long_text, tokenizer, extracted, normalizer))
    assert len(batches) > 1
    assert sum(float(coverage.sum()) for _, coverage in batches) == 3001
    tokenizer.save_pretrained(checkpoint / "tokenizer")
    backbone_config = DebertaV2Config(
        vocab_size=8,
        hidden_size=12,
        num_hidden_layers=1,
        num_attention_heads=3,
        intermediate_size=16,
        max_position_embeddings=512,
        relative_attention=False,
    )
    model = Detector(AutoModel.from_config(backbone_config), fusion_dim=4)
    backbone_config.save_pretrained(checkpoint / "backbone_config")
    torch.save(model.state_dict(), checkpoint / "weights.pt")
    manifest = {
        "schema": "stylometry_24_v1",
        "profile": "light_v1",
        "uses_pos": False,
        "labels": ["human", "ai"],
        "deployment_precision": "fp32_cpu",
        "fusion_dim": 4,
        "model_revisions": {"ai_backbone": config.models.models["ai_backbone"].revision},
        "resource_versions": {
            name: version(name) for name in ("regex", "spacy", "torch", "transformers")
        },
        "normalizer": {"means": [0.0] * 24, "scales": [1.0] * 24, "valid_counts": [10] * 24},
        "calibration": {
            "sentence_temperature": 1.0,
            "document_temperature": 1.0,
            "split": "calibration",
            "precision": "fp32_cpu",
            "artifact_id": "synthetic",
        },
    }
    (checkpoint / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    models = ModelManager(settings, config)
    result = analyze(
        build_document(["hello. hello."]), models, settings, AnalysisContext(time.monotonic() + 60)
    )
    assert result["status"] == "completed" and len(result["findings"]) == 2
    assert 0 <= result["document_score"] <= 1
    assert result["findings"][0]["diagnostics"]["calibration_artifact_id"] == "synthetic"
    from backend.app.schemas.finding import Finding

    finding = Finding.model_validate(result["findings"][0])
    assert finding.confidence_interpretation == "probability_calibrated"
    assert finding.calibration_artifact_id == "synthetic"
    manifest["model_revisions"]["ai_backbone"] = "0" * 40
    with pytest.raises(ValueError, match="revision"):
        validate_manifest(manifest, config)
    manifest["model_revisions"]["ai_backbone"] = config.models.models["ai_backbone"].revision
    manifest["calibration"]["sentence_temperature"] = 0
    with pytest.raises(ValueError, match="temperature"):
        validate_manifest(manifest, config)


def test_model_lease_switch_and_active_unload(settings, monkeypatch):
    models = ModelManager(settings, load_platform_config(settings.config_dir))
    loaded = []
    monkeypatch.setattr(models, "_load", lambda name: loaded.append(name) or ModelBundle(object()))
    with models.lease("dense_retriever"):
        assert models.references == 1
        with pytest.raises(RuntimeError, match="actively"):
            models.unload()
    with models.lease("nli_verifier"):
        assert models.loaded_name == "nli_verifier"
    models.unload()
    assert loaded == ["dense_retriever", "nli_verifier"] and models.loaded is None


def test_temperature_requires_classes_and_fits_positive():
    with pytest.raises(ValueError):
        fit_temperature([[1.0, 2.0]], [1])
    assert (
        0 < fit_temperature([[4.0, 0.0], [0.0, 4.0], [2.0, 0.0], [0.0, 2.0]], [0, 1, 1, 0]) <= 100
    )


def test_metrics_compute_from_labels_with_low_fpr_caution():
    from backend.app.runtime.metrics import binary_metrics

    report = binary_metrics([0, 1], [0.0, 1.0])
    assert report["macro_f1"] == report["roc_auc"] == 1
    assert report["brier"] == report["ece_ai_probability_equal_width_15_bins"] == 0
    assert report["low_fpr_small_sample_caution"]


def test_dense_corpus_is_encoded_once_per_analysis():
    import numpy as np

    calls = []

    class Tokenizer:
        is_fast = True

        def encode(self, text):
            return list(range(len(text.split()) + 2))

        def __call__(self, text, **kwargs):
            import re

            return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}

    class Model:
        tokenizer = Tokenizer()
        max_seq_length = 64

        def encode(self, texts, **kwargs):
            calls.extend(texts)
            return np.array([[1.0, 0.0] for _ in texts])

    class Models:
        @contextmanager
        def lease(self, name):
            yield SimpleNamespace(model=Model())

    retriever = DenseRetriever(Models())
    retriever.search("first", ["passage one", "passage two"])
    retriever.search("second", ["passage one", "passage two"])
    assert calls.count("passage one") == calls.count("passage two") == 1
    retriever.encode([" ".join(["long"] * 150)])
    assert retriever.window_count > 5


def test_onnx_tiny_fixture_export_parity(tmp_path, monkeypatch):
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnx")
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import BertConfig, BertForSequenceClassification, PreTrainedTokenizerFast

    from backend.scripts.export_onnx import main

    model_dir = tmp_path / "cross-encoder"
    BertForSequenceClassification(
        BertConfig(
            vocab_size=4,
            hidden_size=12,
            num_hidden_layers=1,
            num_attention_heads=3,
            intermediate_size=16,
            attn_implementation="eager",
        )
    ).save_pretrained(model_dir)
    core = Tokenizer(WordLevel({"[UNK]": 0, "[PAD]": 1}, unk_token="[UNK]"))
    core.pre_tokenizer = Whitespace()
    PreTrainedTokenizerFast(
        tokenizer_object=core, unk_token="[UNK]", pad_token="[PAD]"
    ).save_pretrained(model_dir)
    output = tmp_path / "fixture.onnx"
    monkeypatch.setattr(
        "sys.argv", ["export_onnx", "--model-dir", str(model_dir), "--output", str(output)]
    )
    main()
    report = json.loads(output.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["providers"] == ["CPUExecutionProvider"]
    assert report["max_abs_logit_difference"] < 1e-5


@pytest.mark.parametrize("name", ["similarity_verifier", "cross_encoder"])
def test_cross_encoder_similarity_activation_and_relevance_logits(name):
    from backend.app.engines.plagiarism.verification import pair_score

    class Models:
        @contextmanager
        def lease(self, requested):
            assert requested == name
            yield SimpleNamespace(
                tokenizer=lambda *args, **kwargs: {"input_ids": torch.ones((1, 8))},
                model=lambda **kwargs: SimpleNamespace(logits=torch.tensor([[2.0]])),
            )

    expected = float(torch.tensor(2.0).sigmoid()) if name == "similarity_verifier" else 2.0
    assert pair_score(Models(), "first", "second", name) == pytest.approx(expected)


def test_oversized_cross_encoder_pair_abstains_without_model_call():
    from backend.app.engines.plagiarism.verification import pair_score

    class Models:
        @contextmanager
        def lease(self, name):
            yield SimpleNamespace(
                tokenizer=lambda *args, **kwargs: {"input_ids": torch.ones((1, 513))},
                model=None,
            )

    assert pair_score(Models(), "first", "second") is None


@pytest.mark.parametrize("input_length,output_length", [(513, 3), (8, 161), (8, 3)])
def test_claim_decomposition_limits_preserve_original_candidate(input_length, output_length):
    from backend.app.engines.hallucination.claim_extraction import extract_claims

    class Tokenizer:
        eos_token_id = 1

        def __call__(self, *args, **kwargs):
            assert kwargs["truncation"] is False
            return {"input_ids": torch.zeros((1, input_length), dtype=torch.long)}

        def decode(self, *args, **kwargs):
            return "\n".join(f"{i}. Proposition {i}." for i in range(1, 7))

    class Model:
        def generate(self, **kwargs):
            assert input_length <= 512
            tokens = torch.zeros((1, output_length), dtype=torch.long)
            if output_length < 160:
                tokens[0, -1] = 1
            return tokens

    class Models:
        def available(self, name):
            return True

        @contextmanager
        def lease(self, name):
            yield SimpleNamespace(model=Model(), tokenizer=Tokenizer())

    text = "Alice did not visit Paris in 2024."
    claims, diagnostics = extract_claims(text, Models())
    assert diagnostics["coverage_limited"]
    assert all(claim.original_text == text for claim in claims)
    if input_length > 512:
        assert diagnostics["decomposition_inputs_over_token_budget"] == 1
        assert claims[0].normalized_claim == text
    elif output_length >= 160:
        assert diagnostics["decomposition_generation_limit_hits"] == 1
        assert claims[0].normalized_claim == text
    else:
        assert len(claims) == 4 and diagnostics["decomposition_propositions_omitted"] == 2
