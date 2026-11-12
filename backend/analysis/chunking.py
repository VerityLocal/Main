"""Nonoverlapping character slices, retokenized with the actual modality tokenizer."""

import re

from backend.analysis.types import AnalysisError, Chunk, Segment, slice_sources
from backend.analysis.languages import syntax_only


def token_count(tokenizer, text, special=False):
    return len(tokenizer(text, add_special_tokens=special, truncation=False, verbose=False)["input_ids"])


def preferred_boundaries(text, kind, language):
    if kind == 'text':
        return [match.end() for match in re.finditer(r'\r?\n[ \t]*\r?\n', text)]
    code = syntax_only(text)
    if language == 'python':
        # Top-level declaration starts end the preceding complete unit. Nested
        # declarations stay with their enclosing function/class where possible.
        return [match.start() for match in re.finditer(r'^(?=@|(?:async\s+)?def\s|class\s)', code, re.M)
                if match.start() > 0]
    if language == 'javascript':
        depth, boundaries = 0, []
        for index, char in enumerate(code):
            depth += char == '{'
            depth -= char == '}'
            if char == '}' and depth == 0:
                end = index+1
                while end < len(text) and text[end] in ';\r\n \t':
                    end += 1
                boundaries.append(end)
        return boundaries
    return []


def split_segment(segment: Segment, tokenizer, budget: int, limit: int | None = None,
                  minimum: int = 0) -> list[Chunk]:
    chunks = []
    start = 0
    text = segment.text
    while start < len(text):
        # Bound retokenization work: never repeatedly tokenize the entire remaining
        # multi-megabyte document. A smaller-than-maximal chunk is safe and explicit.
        remaining = text[start:start+min(65536,budget*16)]
        if token_count(tokenizer, remaining, True) <= budget:
            end = start+len(remaining)
        else:
            # Binary search is an estimate (BPE lengths need not be strictly monotonic).
            # The final selected source slice is always explicitly checked again.
            low, high = 1, len(remaining)
            while low < high:
                mid = (low+high+1)//2
                if token_count(tokenizer, remaining[:mid], True) <= budget:
                    low = mid
                else:
                    high = mid-1
            size = low
            while size > 0 and token_count(tokenizer, remaining[:size], True) > budget:
                size -= 1
            if size == 0:
                raise AnalysisError("token_budget", "Tokenizer cannot fit a source character in the configured budget.")
            boundaries = [end for end in preferred_boundaries(remaining[:size], segment.kind, segment.language)
                          if end >= max(1, size*.2) and token_count(tokenizer, remaining[:end]) >= minimum]
            if not boundaries:
                matches = list(re.finditer(r"\n|(?<=[.!?])\s+" if segment.kind == "text" else r"\n", remaining[:size]))
                boundaries = [match.end() for match in matches if match.end() >= size*.65]
            if boundaries:
                candidate = boundaries[-1]
                if token_count(tokenizer, remaining[:candidate], True) <= budget:
                    size = candidate
            # A tiny final tail can often be avoided by moving the preceding
            # boundary earlier. Never lower minimum-content policy to force a score.
            tail = text[start+size:]
            if minimum and len(tail) <= len(remaining) and token_count(tokenizer, tail) < minimum:
                candidates = sorted(set(boundaries + [m.end() for m in re.finditer(r'\n|(?<=[.!?])\s+', remaining[:size])]), reverse=True)
                for candidate in candidates:
                    left, right = remaining[:candidate], text[start+candidate:]
                    if (minimum <= token_count(tokenizer, left) and minimum <= token_count(tokenizer, right)
                            and token_count(tokenizer, left, True) <= budget and token_count(tokenizer, right, True) <= budget):
                        size = candidate
                        break
            end = start+size
        value = text[start:end]
        content = token_count(tokenizer, value)
        if content:
            if limit is not None and len(chunks) >= limit:
                raise AnalysisError("chunk_limit", "Document exceeds the chunk limit; no subset was scored.")
            chunks.append(Chunk(f"{segment.id}c{len(chunks)+1}", segment.kind, value, content,
                                token_count(tokenizer, value, True), slice_sources(segment.sources, start, end),
                                 segment.section, segment.language, segment.reason if value.strip() else 'whitespace_only'))
        start = end
    return chunks


def make_chunks(segments: list[Segment], tokenizer, kind: str, budget: int, limit: int, minimum: int = 0) -> list[Chunk]:
    chunks = []
    pending = None

    def flush():
        nonlocal pending
        if pending is not None:
            chunks.extend(split_segment(pending, tokenizer, budget, limit-len(chunks), minimum))
            pending = None

    for segment in segments:
        if segment.kind != kind:
            flush()
            continue
        same = pending is not None and (pending.section, pending.language, pending.reason) == (
            segment.section, segment.language, segment.reason)
        if not same:
            flush()
            pending = Segment(segment.id, segment.kind, segment.text, [dict(source) for source in segment.sources],
                              segment.section, segment.language, segment.reason)
        else:
            original = pending.sources and segment.sources and all(source['method']=='source'
                        for source in pending.sources+segment.sources)
            separator = '' if original else '\n\n' if kind == 'text' else '\n'
            offset = len(pending.text)+len(separator)
            pending.text += separator + segment.text
            pending.sources.extend({**source,"start":source["start"]+offset,"end":source["end"]+offset}
                                   for source in segment.sources)
    flush()
    return chunks
