"""Normalization with conservative, many-to-many original-text provenance."""

import unicodedata
from bisect import bisect_left, bisect_right
from importlib.metadata import version
from typing import Literal, Self

import regex
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.document.offsets import Utf16Index


class NormalizationMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    algorithm: Literal["grapheme_nfkc_casefold_whitespace_v1"]
    unicode_version: str
    regex_version: str
    casefold: bool
    trim: bool
    original_utf16_length: int = Field(ge=0)
    normalized_text: str
    original_starts: tuple[int, ...]
    original_ends: tuple[int, ...]

    @field_validator("original_starts", "original_ends", mode="before")
    @classmethod
    def json_arrays(cls, value):
        # FastAPI decodes JSON arrays to lists; freeze their container without
        # coercing the strictly validated integer elements.
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def valid_arrays(self) -> Self:
        if len(self.original_starts) != len(self.normalized_text) or len(self.original_ends) != len(
            self.normalized_text
        ):
            raise ValueError("Each normalized code point requires a source interval")
        previous_start, previous_end = -1, -1
        for start, end in zip(self.original_starts, self.original_ends, strict=True):
            if not 0 <= start < end <= self.original_utf16_length:
                raise ValueError("Invalid normalization source interval")
            if start < previous_start or end < previous_end:
                raise ValueError("Normalization source intervals must be monotonic")
            previous_start, previous_end = start, end
        Utf16Index(self.normalized_text)
        return self

    def normalized_span_to_original(self, start: int, end: int) -> tuple[int, int]:
        if (
            type(start) is not int
            or type(end) is not int
            or not (0 <= start < end <= len(self.normalized_text))
        ):
            raise ValueError("Expected a nonempty normalized code-point span")
        return self.original_starts[start], self.original_ends[end - 1]

    def original_span_to_normalized(
        self, start: int, end: int, *, original_text: str
    ) -> tuple[int, int] | None:
        if (
            type(start) is not int
            or type(end) is not int
            or not (0 <= start < end <= self.original_utf16_length)
        ):
            raise ValueError("Expected a nonempty original UTF-16 span")
        # The map alone cannot tell whether an arbitrary user boundary splits
        # a surrogate pair. Require and validate the original text explicitly.
        self.validate_original(original_text)
        Utf16Index(original_text).slice(start, end)
        first = bisect_right(self.original_ends, start)
        last = bisect_left(self.original_starts, end)
        return (first, last) if first < last else None

    def validate_original(self, text: str) -> None:
        expected = normalize_with_mapping(text, casefold=self.casefold, trim=self.trim)
        if self != expected:
            raise ValueError("Normalization provenance or runtime version does not match original")


def normalize_with_mapping(
    text: str, *, casefold: bool = True, trim: bool = True
) -> NormalizationMap:
    index = Utf16Index(text)
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for cluster in regex.finditer(r"\X", text):
        start, end = index.to_utf16(cluster.start()), index.to_utf16(cluster.end())
        normalized = unicodedata.normalize("NFKC", cluster.group())
        if casefold:
            normalized = normalized.casefold()
        for char in normalized:
            if char.isspace():
                if chars and chars[-1] == " ":
                    ends[-1] = end
                    continue
                char = " "
            chars.append(char)
            starts.append(start)
            ends.append(end)
    lo = 1 if trim and chars and chars[0] == " " else 0
    hi = len(chars) - 1 if trim and chars and chars[-1] == " " else len(chars)
    hi = max(lo, hi)
    return NormalizationMap(
        algorithm="grapheme_nfkc_casefold_whitespace_v1",
        unicode_version=unicodedata.unidata_version,
        regex_version=version("regex"),
        casefold=casefold,
        trim=trim,
        original_utf16_length=index.length,
        normalized_text="".join(chars[lo:hi]),
        original_starts=tuple(starts[lo:hi]),
        original_ends=tuple(ends[lo:hi]),
    )
