"""CPU sentence candidates with explicit Unicode coordinates and limitations."""

import re
from dataclasses import dataclass

from backend.app.document.offsets import Utf16Index


@dataclass(frozen=True)
class Sentence:
    text: str
    start_cp: int
    end_cp: int
    start_offset: int
    end_offset: int


def sentence_spans(text: str) -> list[Sentence]:
    # A deterministic rule-based segmenter, not a multilingual NLP assertion.
    index = Utf16Index(text)
    output = []
    for match in re.finditer(r"[^\n]+?(?:[.!?]+(?=\s|$)|(?=\n|$))", text):
        raw = match.group()
        start = match.start() + len(raw) - len(raw.lstrip())
        end = match.end() - (len(raw) - len(raw.rstrip()))
        if start < end:
            output.append(
                Sentence(text[start:end], start, end, index.to_utf16(start), index.to_utf16(end))
            )
    return output


def passage_spans(text: str, max_chars: int = 1500) -> list[Sentence]:
    index = Utf16Index(text)
    result = []
    for sentence in sentence_spans(text):
        for start in range(sentence.start_cp, sentence.end_cp, max_chars):
            end = min(start + max_chars, sentence.end_cp)
            result.append(
                Sentence(text[start:end], start, end, index.to_utf16(start), index.to_utf16(end))
            )
    return result
