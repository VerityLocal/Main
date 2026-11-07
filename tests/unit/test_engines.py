"""Deterministic algorithms and unavailability; not an accuracy benchmark."""

import json
import time
from types import SimpleNamespace

import pytest

from backend.app.document.chunking import passage_spans, sentence_spans
from backend.app.document.offsets import Utf16Index
from backend.app.engines.ai_detection.inference import analyze as detect
from backend.app.engines.hallucination.bm25_retrieval import BM25
from backend.app.engines.hallucination.claim_extraction import extract_claims, strip_list_marker
from backend.app.engines.hallucination.evidence import aggregate
from backend.app.engines.hallucination.fusion import reciprocal_rank_fusion
from backend.app.engines.plagiarism.alignment import align
from backend.app.engines.plagiarism.minhash import MinHashLSH
from backend.app.engines.plagiarism.winnowing import (
    BASE,
    MASK,
    rolling_hashes,
    stable_hash,
    tokens,
    winnow,
)
from backend.app.engines.stylometry.extractor import FeatureExtractor
from backend.app.engines.stylometry.formulas import entropy, mattr, richness
from backend.app.engines.stylometry.normalization import fit_normalizer, normalize
from backend.app.runtime.inference_queue import AnalysisAborted, AnalysisContext
from backend.scripts.dataset_utils import read_records


class DisabledModels:
    def available(self, name):
        return False


@pytest.mark.parametrize("text", ["😀 Hello! Next?", "One\nTwo", "cafe\u0301!", "中文。\nText."])
def test_chunk_original_utf16(text):
    for span in sentence_spans(text) + passage_spans(text, 3):
        assert Utf16Index(text).slice(span.start_offset, span.end_offset) == span.text


def test_rolling_matches_recomputed_polynomial():
    words = tokens("alpha beta gamma delta epsilon zeta eta")
    expected = []
    for i in range(len(words) - 2):
        value = 0
        for word in words[i : i + 3]:
            value = (value * BASE + stable_hash(word.text)) & MASK
        expected.append(value)
    assert rolling_hashes(words, 3) == expected
    assert winnow([2, 1, 1, 4], 3) == [(1, 2)]
    assert rolling_hashes(words, 10) == []


def test_alignment_normalization_reorders_and_preserves_offsets():
    left = "😀 CAFE\u0301 alpha beta gamma delta. Red blue green yellow black."
    right = "Red blue green yellow black. Café alpha beta gamma delta."
    matches = align(left, right)
    assert len(matches) >= 2
    assert {m["category"] for m in matches} == {"REORDERED_TEXT"}
    for match in matches:
        user = Utf16Index(left).slice(match["start_offset"], match["end_offset"])
        source = Utf16Index(right).slice(match["source_start_offset"], match["source_end_offset"])
        assert [w.text for w in tokens(user)] == [w.text for w in tokens(source)]


def test_minhash_identical_empty_and_parameters():
    index = MinHashLSH()
    text = "One two three four five six seven eight nine ten"
    index.add("same", text)
    index.add("empty", "")
    assert index.query(text)["same"] == 1
    assert index.query("") == {}
    with pytest.raises(ValueError):
        MinHashLSH(bands=10)


@pytest.mark.parametrize(
    "text",
    [
        "Alice visited Paris during the summer of 2024 and toured the city museum.",
        "😀 Café visitors explored the city museum during the summer of 2024!",
    ],
)
def test_complete_lexical_match_is_not_duplicated_as_paraphrase(text, monkeypatch):
    from backend.app.core.config import PROJECT_ROOT, load_platform_config
    from backend.app.document.builder import build_document
    from backend.app.engines.plagiarism import inference
    from backend.app.schemas.analysis import Source

    class Dense:
        window_count = 0

        def __init__(self, *args):
            pass

        def search(self, query, passages, k):
            return [(0, 0.99)], "synthetic_fixture"

    monkeypatch.setattr(inference, "DenseRetriever", Dense)
    calls = []
    monkeypatch.setattr(inference, "pair_score", lambda *args: calls.append(args) or 0.99)
    result = inference.analyze(
        build_document([text]),
        [Source(source_id="reference", title="Fixture", text=text)],
        SimpleNamespace(available=lambda name: True),
        load_platform_config(PROJECT_ROOT / "configs"),
        AnalysisContext(time.monotonic() + 10),
    )
    assert [finding["category"] for finding in result["findings"]] == ["EXACT_OVERLAP"]
    assert not calls
    assert result["diagnostics"]["semantic_candidates_already_aligned"] == 1


@pytest.mark.parametrize("include_exact_passage", [False, True])
def test_partial_matches_and_distinct_source_passages_remain_semantic_candidates(
    include_exact_passage, monkeypatch
):
    from backend.app.core.config import PROJECT_ROOT, load_platform_config
    from backend.app.document.builder import build_document
    from backend.app.engines.plagiarism import inference
    from backend.app.schemas.analysis import Source

    text = "Alice visited Paris during the summer of 2024 and toured the city museum."
    other = "Alice visited Paris during the summer of 2024 and spent her time sketching monuments."
    source_text = text + " " + other if include_exact_passage else other

    class Dense:
        window_count = 0

        def __init__(self, *args):
            pass

        def search(self, query, passages, k):
            return [(index, 0.99) for index in range(len(passages))], "synthetic_fixture"

    monkeypatch.setattr(inference, "DenseRetriever", Dense)
    monkeypatch.setattr(inference, "pair_score", lambda *args: 0.99)
    result = inference.analyze(
        build_document([text]),
        [Source(source_id="reference", title="Fixture", text=source_text)],
        SimpleNamespace(available=lambda name: True),
        load_platform_config(PROJECT_ROOT / "configs"),
        AnalysisContext(time.monotonic() + 10),
    )
    semantic = [f for f in result["findings"] if f["category"] == "SEMANTIC_PARAPHRASE"]
    assert len(semantic) == 1
    assert (
        Utf16Index(source_text).slice(
            semantic[0]["source_start_offset"], semantic[0]["source_end_offset"]
        )
        == other
    )


def test_bm25_empty_and_rrf_rank_not_score():
    assert BM25([]).search("word") == []
    assert BM25(["", "cats chase mice", "dogs bark"]).search("cats")[0][0] == 1
    fused = reciprocal_rank_fusion([["a", "b", "b"], ["b", "a"]])
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert len(fused) == 2


@pytest.mark.parametrize(
    "original,expected",
    [
        ("2024 was warm.", "2024 was warm."),
        ("12.5 percent rose.", "12.5 percent rose."),
        ("-12 degrees.", "-12 degrees."),
        ("1. Earth is round.", "Earth is round."),
        ("• Water freezes.", "Water freezes."),
    ],
)
def test_list_marker_preserves_facts(original, expected):
    assert strip_list_marker(original) == expected


def test_claim_candidates_keep_negation_questions_and_dates():
    text = "😀 Did Alice not visit Paris in 2024? I think Bob may have 12 apples."
    claims, diagnostics = extract_claims(text, DisabledModels())
    assert len(claims) == 2
    assert claims[0].original_text == claims[0].normalized_claim
    assert "not" in claims[0].normalized_claim
    assert claims[0].temporal_expressions == ("2024",)
    assert claims[1].quantities == ("12",)
    assert diagnostics["complete_atomicity_not_established"]


def test_evidence_neutral_unrated_missing_and_conflicting():
    def item(source, label, trust="user_trusted"):
        return {"source_id": source, "reliability": trust, "nli": {label: 0.99}}

    assert aggregate([{"reliability": "user_trusted", "nli": None}]) == "INSUFFICIENT_EVIDENCE"
    assert aggregate([item("a", "neutral")]) == "INSUFFICIENT_EVIDENCE"
    assert aggregate([item("a", "entailment", "unrated")]) == "INSUFFICIENT_EVIDENCE"
    assert aggregate([item("a", "entailment")]) == "SUPPORTED"
    assert aggregate([item("a", "contradiction")]) == "CONTRADICTED"
    assert (
        aggregate([item("a", "entailment"), item("b", "contradiction")]) == "CONFLICTING_EVIDENCE"
    )
    assert (
        aggregate([item("a", "entailment"), item("a", "contradiction")]) == "INSUFFICIENT_EVIDENCE"
    )


def test_features_exact_24_missingness_and_training_only_normalization():
    extractor = FeatureExtractor()
    result = extractor.extract("😀 A short sentence! Another sentence.", "fr")
    for row in result["sentences"]:
        assert len(row["features"]) == len(row["feature_valid_mask"]) == 24
        assert row["features"][5:8] == [None] * 3
        assert row["features"][12:24] == [None] * 12
    normalizer = fit_normalizer([[2.0] + [None] * 23, [4.0] + [None] * 23])
    values, mask = normalize([4.0] + [None] * 23, normalizer)
    assert values[:2] == [1, 0] and mask[:2] == [True, False]
    with pytest.raises(ValueError):
        normalize([2.0, 1.0] + [None] * 22, normalizer)
    with pytest.raises(ValueError):
        FeatureExtractor(profile="full_v1")
    assert mattr(["a"] * 49) is None
    assert mattr(["a"] * 50) == 1 / 50
    assert richness(["a"] * 50)[0] == 9800
    assert entropy([1, 1]) == 1


def test_detector_never_uses_base_model_without_checkpoint(document):
    result = detect(document, DisabledModels(), SimpleNamespace(detector_checkpoint=None), None)
    assert result["status"] == "unavailable" and result["findings"] == []


def test_cancellation_and_deadlines():
    context = AnalysisContext(time.monotonic() + 60)
    context.check()
    context.cancelled.set()
    with pytest.raises(AnalysisAborted, match="cancelled"):
        context.check()
    with pytest.raises(AnalysisAborted, match="deadline"):
        AnalysisContext(time.monotonic() - 1).check()


def test_dataset_split_leakage_rejected(tmp_path):
    path = tmp_path / "data.jsonl"
    records = [
        {"id": "a", "group_id": "one", "split": "train", "text": "Same Text"},
        {"id": "b", "group_id": "two", "split": "final_test", "text": " same  text "},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    with pytest.raises(ValueError, match="leakage"):
        read_records(path)
