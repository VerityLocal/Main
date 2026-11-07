"""Checked UTF-16 index salvaged from backend/app/document/offsets.py; new segmentation."""
import re
from bisect import bisect_left


class Utf16Index:
    def __init__(self, text):
        self.text = text
        positions = [0]
        for char in text:
            point = ord(char)
            if 0xD800 <= point <= 0xDFFF:
                raise ValueError("Invalid text encoding")
            positions.append(positions[-1] + (2 if point > 0xFFFF else 1))
        self.boundaries = positions

    def offset(self, cp):
        return self.boundaries[cp]

    def slice(self, start, end):
        a, b = bisect_left(self.boundaries, start), bisect_left(self.boundaries, end)
        if a >= len(self.boundaries) or b >= len(self.boundaries):
            raise ValueError("Invalid range")
        if self.boundaries[a] != start or self.boundaries[b] != end or start > end:
            raise ValueError("Invalid range")
        return self.text[a:b]


def words(text):
    return re.findall(r"\w+", text.casefold())


def segment(text, max_chars=1600):
    """Sentence/block candidates, preserving the original text. Long blocks split at spaces."""
    index = Utf16Index(text)
    rows = []
    # Paragraph boundaries are authoritative; a code paragraph is not split at punctuation.
    for paragraph in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
        value = paragraph.group().rstrip()
        code = bool(re.search(r"(^|\n)\s*(def |class |import |function |const |public |#include)|[{};].*[{};]", value))
        candidates = [(0, len(value))] if code else [
            (m.start(), m.end()) for m in re.finditer(r"[\s\S]+?(?:[.!?]+[\"'”’)]*(?=\s|$)|$)", value) if m.group().strip()
        ]
        for first, last in candidates:
            while first < last:
                while first < last and value[first].isspace():
                    first += 1
                end = min(first + max_chars, last)
                if end < last:
                    cut = value.rfind(" ", first + max_chars // 2, end)
                    if cut > first:
                        end = cut
                while end > first and value[end - 1].isspace():
                    end -= 1
                if end <= first:
                    break
                start_cp, end_cp = paragraph.start() + first, paragraph.start() + end
                excerpt = text[start_cp:end_cp]
                rows.append({"id": f"s{len(rows)}", "start": index.offset(start_cp), "end": index.offset(end_cp), "text": excerpt, "kind": "code" if code else "text", "words": len(words(excerpt))})
                first = end
    return rows


def aggregate(rows, key):
    total = sum(row["words"] for row in rows)
    scored = [row for row in rows if row[key].get("score") is not None]
    covered = sum(row["words"] for row in scored)
    percent = 100 * sum(row["words"] * row[key]["score"] for row in scored) / covered if covered else None
    return {"percent": percent, "coverage": covered / total if total else 0, "scored_segments": len(scored), "total_segments": len(rows)}
