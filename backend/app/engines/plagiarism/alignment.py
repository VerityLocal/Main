"""Token sequence alignment, independent of neural verifier scores."""

from difflib import SequenceMatcher

from backend.app.engines.plagiarism.winnowing import tokens


def align(user: str, source: str, min_words: int = 5) -> list[dict]:
    left, right = tokens(user), tokens(source)
    matcher = SequenceMatcher(None, [w.text for w in left], [w.text for w in right], autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= min_words]
    # Also recover fragments excluded by global ordering, using shingle anchors.
    right_shingles = {}
    for i in range(len(right) - min_words + 1):
        right_shingles.setdefault(tuple(w.text for w in right[i : i + min_words]), []).append(i)
    covered = {(b.a, b.b, b.size) for b in blocks}
    for i in range(len(left) - min_words + 1):
        key = tuple(w.text for w in left[i : i + min_words])
        for j in right_shingles.get(key, [])[:8]:
            size = min_words
            while (
                i + size < len(left)
                and j + size < len(right)
                and left[i + size].text == right[j + size].text
            ):
                size += 1
            if not any(
                a <= i and i + size <= a + n and b <= j and j + size <= b + n for a, b, n in covered
            ):
                covered.add((i, j, size))
    fragments = sorted(covered)
    reordered = any(fragments[i][1] > fragments[i + 1][1] for i in range(len(fragments) - 1))
    return [
        {
            "start_offset": left[a].start,
            "end_offset": left[a + n - 1].end,
            "source_start_offset": right[b].start,
            "source_end_offset": right[b + n - 1].end,
            "category": "REORDERED_TEXT" if reordered else "EXACT_OVERLAP",
            "matched_words": n,
        }
        for a, b, n in fragments
    ]
