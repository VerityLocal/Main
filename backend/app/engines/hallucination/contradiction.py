"""Restrict intrinsic candidates before NLI; temporal differences are not contradictions."""

from backend.app.engines.hallucination.bm25_retrieval import BM25


def related_pairs(claims, models, context):
    pairs = set()
    if models.available("dense_retriever") and claims:
        from backend.app.engines.plagiarism.dense_retrieval import DenseRetriever

        vectors = DenseRetriever(models, context.check).encode(
            [claim.normalized_claim for claim in claims]
        )
        for i in range(len(claims)):
            context.check()
            ranked = sorted(range(len(claims)), key=lambda j: -float(vectors[i] @ vectors[j]))[:5]
            for j in ranked:
                if i != j:
                    pairs.add(tuple(sorted((i, j))))
    else:
        index = BM25([claim.normalized_claim for claim in claims])
        for i, claim in enumerate(claims):
            for j, _ in index.search(claim.normalized_claim, 5):
                if i != j:
                    pairs.add(tuple(sorted((i, j))))
    output = []
    for i, j in sorted(pairs):
        left, right = claims[i], claims[j]
        if left.normalized_claim.casefold() == right.normalized_claim.casefold():
            continue
        if (
            left.temporal_expressions
            and right.temporal_expressions
            and not set(left.temporal_expressions) & set(right.temporal_expressions)
        ):
            continue
        if left.entities and right.entities and not set(left.entities) & set(right.entities):
            continue
        output.append((i, j))
    return output
