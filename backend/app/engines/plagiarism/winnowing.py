"""Deterministic rolling word hashes and rightmost-minimum winnowing."""

import hashlib
from collections import deque
from dataclasses import dataclass

import regex

from backend.app.document.normalization import normalize_with_mapping

MASK = (1 << 64) - 1
BASE = 1_000_003


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def tokens(text: str) -> list[Token]:
    mapping = normalize_with_mapping(text)
    result = []
    for match in regex.finditer(r"[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*", mapping.normalized_text):
        start, end = mapping.normalized_span_to_original(match.start(), match.end())
        result.append(Token(match.group(), start, end))
    return result


def stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def rolling_hashes(words: list[Token], k: int = 5) -> list[int]:
    if k < 1:
        raise ValueError("k must be positive")
    if len(words) < k:
        return []
    values = [stable_hash(word.text) for word in words]
    power = pow(BASE, k - 1, 1 << 64)
    value = 0
    for item in values[:k]:
        value = (value * BASE + item) & MASK
    output = [value]
    for i in range(k, len(values)):
        value = ((value - values[i - k] * power) * BASE + values[i]) & MASK
        output.append(value)
    return output


def winnow(hashes: list[int], window: int = 4) -> list[tuple[int, int]]:
    if window < 1:
        raise ValueError("Window must be positive")
    if not hashes:
        return []
    window = min(window, len(hashes))
    queue: deque[int] = deque()
    output = []
    for i, value in enumerate(hashes):
        while queue and hashes[queue[-1]] >= value:
            queue.pop()
        queue.append(i)
        while queue[0] <= i - window:
            queue.popleft()
        if i >= window - 1 and (not output or output[-1][1] != queue[0]):
            output.append((hashes[queue[0]], queue[0]))
    return output
