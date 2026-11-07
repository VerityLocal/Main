"""The same unique-coverage window aggregation for training and deployment."""

import torch

from backend.app.engines.ai_detection.windows import window_batches


def document_forward(
    model, text, tokenizer, extracted, normalizer, check=lambda: None, max_windows=64
):
    rows = len(extracted["sentences"])
    if not rows:
        raise ValueError("Document has no sentence candidates")
    device = next(model.parameters()).device
    representation_sum = None
    weights = torch.zeros(rows, device=device)
    for i, (batch, coverage) in enumerate(window_batches(text, tokenizer, extracted, normalizer)):
        if i >= max_windows:
            raise ValueError("Document exceeds configured window budget; not silently truncated")
        check()
        batch = {key: value.to(device) for key, value in batch.items()}
        coverage = coverage.to(device)
        representation, _valid = model.representations(**batch)
        weighted = representation * coverage[None, :, None]
        representation_sum = (
            weighted if representation_sum is None else representation_sum + weighted
        )
        weights += coverage
    pooled = representation_sum / weights.clamp_min(1)[None, :, None]
    sentence, document = model.classify(pooled, weights[None, :] > 0, weights[None, :])
    return sentence[0], document[0], weights > 0
