"""Reciprocal Rank Fusion uses ranks, not incompatible score scales."""


def reciprocal_rank_fusion(rankings, k0=60):
    if k0 <= 0:
        raise ValueError("k0 must be positive")
    scores = {}
    for ranking in rankings:
        seen = set()
        for rank, item in enumerate(ranking, 1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0) + 1 / (k0 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
