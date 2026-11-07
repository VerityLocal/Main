"""Cross-encoder STS scoring, not a calibrated paraphrase/misconduct classifier."""


def pair_score(models, left, right, name="similarity_verifier"):
    import torch

    with models.lease(name) as bundle:
        encoded = bundle.tokenizer(left, right, truncation=False, return_tensors="pt")
        if encoded["input_ids"].shape[-1] > 512:
            return None  # Abstain instead of silently scoring a prefix.
        with torch.inference_mode():
            logits = bundle.model(**encoded).logits
        if logits.numel() != 1 or not bool(torch.isfinite(logits).all()):
            raise ValueError("Expected one finite cross-encoder logit")
        score = logits.reshape(-1)[0]
        # The pinned STSB checkpoint uses CrossEncoder's one-label sigmoid
        # default. Reproduce its [0, 1] similarity scale, not a probability.
        # Keep MS MARCO relevance logits raw: they are ranking-only scores.
        return float(score.sigmoid() if name == "similarity_verifier" else score)
