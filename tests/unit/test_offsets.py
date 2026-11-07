import pytest

from backend.app.document.offsets import Utf16Index, utf16_length


@pytest.mark.parametrize("text", ["", "ASCII", "café", "e\u0301", "😀", "A😀𐐀B", "हिन्दी", "\r\n\t"])
def test_roundtrip_every_scalar_boundary(text):
    index = Utf16Index(text)
    assert index.length == len(text.encode("utf-16-le")) // 2
    for cp in range(len(text) + 1):
        assert index.to_code_point(index.to_utf16(cp)) == cp


def test_non_bmp_browser_slice():
    index = Utf16Index("a😀b")
    assert index.boundaries == (0, 1, 3, 4)
    assert index.slice(1, 3) == "😀"
    assert utf16_length("😀") == 2


@pytest.mark.parametrize("position", [-1, 2, 5, True, 1.5])
def test_invalid_utf16_boundary(position):
    with pytest.raises(ValueError):
        Utf16Index("a😀b").to_code_point(position)


@pytest.mark.parametrize("position", [-1, 4, True, 1.5])
def test_invalid_codepoint_boundary(position):
    with pytest.raises(ValueError):
        Utf16Index("a😀b").to_utf16(position)


@pytest.mark.parametrize("text", ["\ud800", "\udfff", "x\ud800y"])
def test_unpaired_surrogates_rejected(text):
    with pytest.raises(ValueError):
        Utf16Index(text)


def test_reversed_and_empty_span():
    with pytest.raises(ValueError):
        Utf16Index("abc").slice(2, 1)
    assert Utf16Index("abc").slice(1, 1) == ""
