"""Checked Unicode scalar/code-point and UTF-16 coordinate conversion."""

from bisect import bisect_left
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Utf16Index:
    text: str
    boundaries: tuple[int, ...] = field(init=False)

    def __post_init__(self) -> None:
        positions = [0]
        for char in self.text:
            point = ord(char)
            if 0xD800 <= point <= 0xDFFF:
                raise ValueError("Unpaired surrogate code points are not accepted")
            positions.append(positions[-1] + (2 if point > 0xFFFF else 1))
        object.__setattr__(self, "boundaries", tuple(positions))

    @property
    def length(self) -> int:
        return self.boundaries[-1]

    def to_utf16(self, code_point_offset: int) -> int:
        if type(code_point_offset) is not int or not 0 <= code_point_offset < len(self.boundaries):
            raise ValueError("Invalid code-point boundary")
        return self.boundaries[code_point_offset]

    def to_code_point(self, utf16_offset: int) -> int:
        if type(utf16_offset) is not int or not 0 <= utf16_offset <= self.length:
            raise ValueError("Invalid UTF-16 boundary")
        index = bisect_left(self.boundaries, utf16_offset)
        if self.boundaries[index] != utf16_offset:
            raise ValueError("UTF-16 boundary splits a surrogate pair")
        return index

    def slice(self, start: int, end: int) -> str:
        if start > end:
            raise ValueError("Span is reversed")
        return self.text[self.to_code_point(start) : self.to_code_point(end)]


def utf16_length(text: str) -> int:
    return Utf16Index(text).length
