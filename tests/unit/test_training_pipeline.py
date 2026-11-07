"""A tiny, synthetic two-head training/calibration/deployment roundtrip."""

import json
import time

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")

from backend.app.core.config import load_platform_config  # noqa: E402
from backend.app.document.builder import build_document  # noqa: E402
from backend.app.document.chunking import sentence_spans  # noqa: E402
from backend.app.engines.ai_detection.inference import analyze  # noqa: E402
from backend.app.runtime.inference_queue import AnalysisContext  # noqa: E402
from backend.app.runtime.metrics import classification_summary  # noqa: E402
from backend.app.services.model_manager import ModelManager  # noqa: E402
from backend.scripts import evaluate, train_ai_detector  # noqa: E402
from backend.scripts.dataset_utils import dataset_provenance, file_sha256  # noqa: E402


def test_real_training_cli_calibration_and_shared_cpu_deployment(
    tmp_path, settings_factory, monkeypatch
):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import AutoModel, DebertaV2Config, PreTrainedTokenizerFast

    settings = settings_factory(detector_checkpoint=tmp_path / "checkpoint")
    config = load_platform_config(settings.config_dir)
    spec = config.models.models["ai_backbone"]
    path = settings.model_cache / "ai_backbone" / spec.revision
    path.mkdir(parents=True)
    core = Tokenizer(
        WordLevel({"[UNK]": 0, "[PAD]": 1, "alpha": 2, "beta": 3, ".": 4}, unk_token="[UNK]")
    )
    core.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=core, unk_token="[UNK]", pad_token="[PAD]")
    tokenizer.save_pretrained(path)
    AutoModel.from_config(
        DebertaV2Config(
            vocab_size=8,
            hidden_size=12,
            num_hidden_layers=1,
            num_attention_heads=3,
            intermediate_size=16,
            max_position_embeddings=512,
            relative_attention=False,
        )
    ).save_pretrained(path)
    (path / ".download-complete").write_text(spec.revision, encoding="ascii")
    rows = []
    for split, count in [("train", 4), ("validation", 2), ("calibration", 2), ("final_test", 2)]:
        for i in range(count):
            text = f"alpha {split} {i}. beta words."
            # Numeric test targets, not assertions of real-world authorship.
            rows.append(
                {
                    "id": f"{split}-{i}",
                    "group_id": f"{split}-{i}",
                    "split": split,
                    "text": text,
                    "language": "en",
                    "label": i % 2,
                    "document_label_policy": "contains_annotated_ai_v1",
                    "sentence_labels": [
                        {"start_offset": s.start_offset, "end_offset": s.end_offset, "label": i % 2}
                        for s in sentence_spans(text)
                    ],
                }
            )
    data = tmp_path / "fixture.jsonl"
    data.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    checkpoint = settings.detector_checkpoint
    monkeypatch.setattr(train_ai_detector, "Settings", lambda: settings)
    monkeypatch.setattr(
        "sys.argv",
        [
            "train_ai_detector",
            "--data",
            str(data),
            "--output",
            str(checkpoint),
            "--epochs",
            "1",
            "--accumulation",
            "2",
            "--fusion-dim",
            "4",
            "--max-windows",
            "1",
        ],
    )
    train_ai_detector.main()
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selected_epoch"] == 1
    assert manifest["training_execution"]["optimizer_steps"] == 2
    assert manifest["dataset_provenance"]["data_sha256"] == file_sha256(data)
    selected = [row for row in rows if row["split"] == "calibration"]
    models = ModelManager(settings, config)
    logits, _, _ = evaluate.collect_logits(selected, checkpoint, manifest, models)
    deployment = analyze(
        build_document([selected[0]["text"]], language="en"),
        models,
        settings,
        AnalysisContext(time.monotonic() + 60),
    )
    assert deployment["document_score"] == pytest.approx(evaluate.probabilities(logits, 1)[0])
    assert (
        deployment["diagnostics"]["document_score_interpretation"]
        == "estimated_probability_contains_annotated_ai"
    )
    monkeypatch.setattr(evaluate, "Settings", lambda **_: settings)
    for split in ("calibration", "final_test"):
        args = [
            "evaluate",
            "--data",
            str(data),
            "--checkpoint",
            str(checkpoint),
            "--split",
            split,
            "--output",
            str(tmp_path / f"{split}.json"),
        ]
        if split == "calibration":
            args.append("--fit-calibration")
        monkeypatch.setattr("sys.argv", args)
        evaluate.main()
    final = json.loads((tmp_path / "final_test.json").read_text(encoding="utf-8"))
    assert final["calibrated"] and final["records"] == 2
    assert final["execution"] == {"device": "cpu", "precision": "fp32", "checkpoint_loads": 1}
    assert final["sentence_metrics"]["records"] == 4
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["calibration"]["document_temperature"] > 0
    assert manifest["calibration"]["sentence_temperature"] > 0
    assert "calibration" in manifest["seen_split_identities"]
    assert "final_test" not in manifest["seen_split_identities"]
    # An input beyond the explicit pilot profile must not receive calibrated confidence.
    manifest["input_profile"] = {"max_tokens": 2}
    (checkpoint / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = analyze(
        build_document([selected[0]["text"]]),
        models,
        settings,
        AnalysisContext(time.monotonic() + 60),
    )
    assert result["status"] == "unavailable" and result["findings"] == []


def test_dataset_manifest_tampering_and_mixed_policy_rejected(tmp_path):
    data = tmp_path / "data.jsonl"
    data.write_text("original\n", encoding="utf-8")
    data.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "output_sha256": file_sha256(data),
                "document_label_policy": "contains_annotated_ai_v1",
            }
        ),
        encoding="utf-8",
    )
    rows = [{"document_label_policy": "contains_annotated_ai_v1"}]
    assert dataset_provenance(data, rows)["import_manifest"]
    data.write_text("modified\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        dataset_provenance(data, rows)
    with pytest.raises(ValueError, match="one supported"):
        dataset_provenance(data, rows + [{"document_label_policy": "binary_authorship_v1"}])


def test_false_positive_and_one_class_metrics_are_observed_rates():
    report = classification_summary([0, 0, 1, 1], [0.2, 0.8, 0.4, 0.9])
    assert report["confusion_matrix_at_0_5"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert report["human_false_positive_rate_at_0_5"] == 0.5
    assert report["ai_recall_at_0_5"] == 0.5
    human = classification_summary([0, 0], [0.1, 0.6])
    assert human["human_false_positive_rate_at_0_5"] == 0.5
    assert human["ai_recall_at_0_5"] is None
