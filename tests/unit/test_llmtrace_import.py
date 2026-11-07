"""Span semantics and leakage joins checked independently of implementation."""

import random
from array import array
from collections import Counter

import pytest

from backend.app.document.offsets import Utf16Index
from backend.scripts.dataset_grouping import Components, group_records, near_duplicate_components
from backend.scripts.prepare_llmtrace import assign_splits, balanced_sample, convert_annotations


def test_supplied_spans_drive_sentence_labels_and_astral_offsets():
    text = "Hi 😀. AI words. Human words."
    start = text.index("AI")
    end = text.index(" Human")
    result = convert_annotations(
        {"text": text, "label": "mixed", "ai_char_intervals": [[start, end]]}
    )
    assert result["label"] == 1
    assert [s["label"] for s in result["sentence_labels"]] == [0, 1, 0]
    assert result["ai_spans_utf16"] == [[start + 1, end + 1]]
    annotated = result["sentence_labels"][1]
    assert Utf16Index(text).slice(annotated["start_offset"], annotated["end_offset"]) == "AI words."


def test_partial_sentence_is_masked_and_whitespace_does_not_create_false_gaps():
    text = "AI words. Human words."
    partial = convert_annotations({"text": text, "label": "mixed", "ai_char_intervals": [[0, 2]]})
    assert partial["label"] == 1
    assert [row["label"] for row in partial["sentence_labels"]] == [0]
    assert partial["sentence_supervision"] == {"masked_partial": 1, "human": 1}
    complete = convert_annotations(
        {"text": text, "label": "mixed", "ai_char_intervals": [[3, 9], [0, 2], [0, 2]]}
    )
    assert [row["label"] for row in complete["sentence_labels"]] == [1, 0]


@pytest.mark.parametrize("interval", [[-1, 2], [0, 100], [2, 2], [3, 1], [False, 2], [0, 1.5]])
def test_invalid_intervals_are_rejected(interval):
    with pytest.raises(ValueError, match="invalid_code_point_interval"):
        convert_annotations(
            {"text": "Some text.", "label": "mixed", "ai_char_intervals": [interval]}
        )


@pytest.mark.parametrize("label,intervals", [("human", [[0, 3]]), ("mixed", []), ("ai", [[0, 3]])])
def test_inconsistent_document_labels_are_not_silently_repaired(label, intervals):
    with pytest.raises(ValueError):
        convert_annotations({"text": "Some text.", "label": label, "ai_char_intervals": intervals})


def test_prefix_join_matches_exhaustive_jaccard_components():
    rng = random.Random(77)
    sets = []
    for size in [1, 5, 12, 30, 80]:
        for _ in range(8):
            base = set(rng.sample(range(500), size))
            sets.append(base)
            sets.append(base | set(rng.sample(range(500), max(1, size // 12))))
            sets.append(set(sorted(base)[max(1, size // 10) :]))
    for threshold in (60, 85, 100):
        expected = Components(len(sets))
        for i, left in enumerate(sets):
            for j, right in enumerate(sets[:i]):
                if left and right and 100 * len(left & right) >= threshold * len(left | right):
                    expected.union(i, j)
        actual = Components(len(sets))
        near_duplicate_components(
            [array("Q", sorted(values)) for values in sets], actual, threshold
        )
        assert [actual.find(i) for i in range(len(sets))] == [
            expected.find(i) for i in range(len(sets))
        ]


def test_related_development_text_never_enters_reserved_test_or_calibration_training():
    base = " ".join(f"word{i}" for i in range(120))
    records = [
        {"id": "train1", "topic_id": "a", "text": base, "upstream_split": "train"},
        {"id": "test1", "topic_id": "b", "text": base + " additional", "upstream_split": "test"},
        {"id": "train2", "topic_id": "c", "text": "Unique source.", "upstream_split": "train"},
        {"id": "valid1", "topic_id": "c", "text": "Source rewrite.", "upstream_split": "valid"},
        {"id": "train3", "topic_id": "d", "text": "Different example.", "upstream_split": "train"},
    ]
    roots, stats = group_records(records)
    assert roots[0] == roots[1] and roots[2] == roots[3]
    assert stats["near_duplicate_component_merges"] == 1
    splits, audit = assign_splits(records, roots, seed=42)
    assert splits[:3] == [None, "final_test", None]
    assert splits[3] in {"validation", "calibration"} and splits[4] == "train"
    assert audit["cross_upstream_split_components"] == 2


def test_hierarchical_sampling_balances_authorship_before_generator_count():
    rows = []
    for label in ("human", "ai", "mixed"):
        for domain in ("news", "review"):
            for i in range(60):
                rows.append(
                    {
                        "id": f"{label}-{domain}-{i}",
                        "source_label": label,
                        "domain": domain,
                        "generator": "human" if label == "human" else f"model{i % 12}",
                        "token_count": 100 + 10 * i % 400,
                    }
                )
    first = balanced_sample(rows, 120, 42)
    assert Counter(row["source_label"] for row in first) == {"human": 40, "ai": 40, "mixed": 40}
    assert len({row["id"] for row in first}) == 120
    assert first == balanced_sample(list(reversed(rows)), 120, 42)
