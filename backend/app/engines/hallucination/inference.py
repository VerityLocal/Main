"""BM25/BGE/RRF evidence retrieval followed by reranking and NLI."""

from backend.app.document.chunking import passage_spans
from backend.app.engines.hallucination.bm25_retrieval import BM25
from backend.app.engines.hallucination.claim_extraction import extract_claims
from backend.app.engines.hallucination.contradiction import related_pairs
from backend.app.engines.hallucination.evidence import aggregate
from backend.app.engines.hallucination.fusion import reciprocal_rank_fusion
from backend.app.engines.hallucination.nli import verify
from backend.app.engines.plagiarism.dense_retrieval import DenseRetriever
from backend.app.engines.plagiarism.verification import pair_score


def analyze(document, sources, models, config, context, emit_partial):
    claims, diagnostics = extract_claims(document.extracted_text, models, check=context.check)
    pairs = related_pairs(claims, models, context)
    passages = [(source, span) for source in sources for span in passage_spans(source.text)]
    index = BM25([span.text for _, span in passages])
    dense = DenseRetriever(models, context.check)
    retrieved = []
    for claim in claims:
        context.check()
        rankings = [[i for i, _ in index.search(claim.normalized_claim, 8)]]
        if passages and models.available("dense_retriever"):
            ranking, backend = dense.search(
                claim.normalized_claim, [span.text for _, span in passages]
            )
            rankings.append([i for i, _ in ranking])
            diagnostics["dense_backend"] = backend
        merged = [i for i, _ in reciprocal_rank_fusion(rankings, config.retrieval.rrf.k0)[:8]]
        retrieved.append(merged)
    if models.available("cross_encoder"):
        for claim, candidates in zip(claims, retrieved, strict=True):
            context.check()
            scores = {
                i: pair_score(models, passages[i][1].text, claim.normalized_claim, "cross_encoder")
                for i in candidates
            }
            candidates.sort(key=lambda i: -(scores[i] if scores[i] is not None else -1e30))
    outputs = []
    nli_available = models.available("nli_verifier")
    for claim, candidates in zip(claims, retrieved, strict=True):
        context.check()
        evidence = []
        for i in candidates[:4]:
            source, span = passages[i]
            context.check()
            scores = verify(models, span.text, claim.normalized_claim) if nli_available else None
            evidence.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "publication_date": source.publication_date,
                    "retrieved_at": source.retrieved_at.isoformat()
                    if source.retrieved_at
                    else None,
                    "reliability": source.reliability,
                    "passage": span.text,
                    "source_start_offset": span.start_offset,
                    "source_end_offset": span.end_offset,
                    "nli": scores,
                    "nli_unavailable_or_pair_over_token_budget": scores is None,
                }
            )
        result = {
            **claim.model_dump(mode="json"),
            "finding_id": claim.claim_id,
            "document_id": document.document_id,
            "revision": document.revision,
            "offset_unit": "utf16_code_unit",
            "category": aggregate(evidence),
            "evidence": evidence,
            "confidence": None,
            "diagnostics": {
                "candidate_only": True,
                "threshold": "0.85_proposed_not_calibrated",
                "source_trust": "user_asserted_not_independently_verified",
                "nli_available": nli_available,
            },
        }
        outputs.append(result)
        emit_partial({"finding": result})
    contradictions = []
    if nli_available:
        for i, j in pairs:
            context.check()
            if len(contradictions) >= 48:
                diagnostics["intrinsic_output_limited"] = True
                break
            scores = verify(models, claims[i].normalized_claim, claims[j].normalized_claim)
            if scores and scores["contradiction"] >= 0.85:
                contradictions.append(
                    {
                        "left": claims[i].model_dump(mode="json"),
                        "right": claims[j].model_dump(mode="json"),
                        "nli": scores,
                        "candidate_only": True,
                    }
                )
    diagnostics["intrinsic_candidate_pairs"] = len(pairs)
    diagnostics["nli_available"] = nli_available
    diagnostics["dense_token_windows"] = dense.window_count
    diagnostics["dense_pooling"] = "unique_token_weighted_window_embeddings"
    return {
        "status": "completed",
        "findings": outputs,
        "intrinsic_contradictions": contradictions,
        "diagnostics": diagnostics,
    }
