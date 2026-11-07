import pytest
from pydantic import ValidationError

from backend.app.document.normalization import NormalizationMap, normalize_with_mapping


@pytest.mark.parametrize(
    ("original", "normalized"),
    [
        ("  A\t\r\n B  ", "a b"),
        ("Straße ﬁ", "strasse fi"),
        ("Cafe\u0301 😀", "café 😀"),
        ("ＡＢＣ", "abc"),
        ("", ""),
        (" \t\n", ""),
    ],
)
def test_normalized_text_and_json_roundtrip(original, normalized):
    mapping = normalize_with_mapping(original)
    assert mapping.normalized_text == normalized
    assert NormalizationMap.model_validate_json(mapping.model_dump_json()) == mapping
    mapping.validate_original(original)


def test_expansion_mapping_is_conservative():
    mapping = normalize_with_mapping("ß😀")
    assert mapping.normalized_text == "ss😀"
    assert mapping.normalized_span_to_original(0, 1) == (0, 1)
    assert mapping.normalized_span_to_original(1, 2) == (0, 1)
    assert mapping.normalized_span_to_original(2, 3) == (1, 3)
    assert mapping.original_span_to_normalized(0, 1, original_text="ß😀") == (0, 2)
    with pytest.raises(ValueError):
        mapping.original_span_to_normalized(2, 3, original_text="ß😀")


def test_combining_cluster_covers_original():
    mapping = normalize_with_mapping("e\u0301")
    assert mapping.normalized_span_to_original(0, 1) == (0, 2)
    assert mapping.original_span_to_normalized(1, 2, original_text="e\u0301") == (0, 1)


def test_whitespace_run_and_trim_provenance():
    original = "  A \t\n B  "
    mapping = normalize_with_mapping(original)
    assert mapping.normalized_text == "a b"
    assert mapping.normalized_span_to_original(1, 2) == (3, 7)
    assert mapping.original_span_to_normalized(0, 2, original_text=original) is None
    assert mapping.original_span_to_normalized(3, 7, original_text=original) == (1, 2)


def test_options_are_persisted():
    mapping = normalize_with_mapping("  Aß  ", casefold=False, trim=False)
    assert mapping.normalized_text == " Aß "
    assert not mapping.casefold and not mapping.trim
    mapping.validate_original("  Aß  ")


@pytest.mark.parametrize("span", [(-1, 1), (0, 0), (2, 1), (0, 4), (False, 1)])
def test_invalid_normalized_spans(span):
    with pytest.raises(ValueError):
        normalize_with_mapping("abc").normalized_span_to_original(*span)


def test_corrupted_and_runtime_mismatched_maps():
    mapping = normalize_with_mapping("abc")
    for update in [{"normalized_text": "xyz"}, {"unicode_version": "wrong"}]:
        corrupted = mapping.model_copy(update=update)
        with pytest.raises(ValueError):
            corrupted.validate_original("abc")
    with pytest.raises(ValidationError):
        NormalizationMap.model_validate({**mapping.model_dump(), "original_starts": (2, 1, 0)})


def test_map_elements_are_strict_integers():
    mapping = normalize_with_mapping("a").model_dump(mode="json")
    mapping["original_starts"] = ["0"]
    with pytest.raises(ValidationError):
        NormalizationMap.model_validate(mapping)
