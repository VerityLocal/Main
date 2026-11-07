"""CPU causal token scoring with ID-ascending logit ties and original offsets."""

import math
import statistics


class ReferenceScorer:
    def __init__(self, models, context=512):
        self.models, self.context = models, context

    def __call__(self, text, start_cp, end_cp):
        import torch

        log_probabilities, log_ranks = [], []
        with self.models.lease("reference_lm") as bundle:
            if not bundle.tokenizer.is_fast:
                raise ValueError("Reference features require a fast tokenizer with offsets")
            encoded = bundle.tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
            ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
            special = set(bundle.tokenizer.all_special_ids)
            for i, (token, (start, end)) in enumerate(zip(ids, offsets, strict=True)):
                if i == 0 or token in special or not start_cp <= start < end <= end_cp:
                    continue
                context_ids = ids[max(0, i - self.context + 1) : i + 1]
                inputs = torch.tensor([context_ids], dtype=torch.long)
                with torch.inference_mode():
                    logits = (
                        bundle.model(input_ids=inputs, attention_mask=torch.ones_like(inputs))
                        .logits[0, -2]
                        .float()
                    )
                probability = float(logits.log_softmax(-1)[token])
                vocabulary_ids = torch.arange(logits.numel())
                rank = 1 + int(
                    (
                        (logits > logits[token])
                        | ((logits == logits[token]) & (vocabulary_ids < token))
                    ).sum()
                )
                log_probabilities.append(probability)
                log_ranks.append(math.log(rank))
        return [
            statistics.mean(log_probabilities) if log_probabilities else None,
            statistics.pvariance(log_probabilities) if len(log_probabilities) > 1 else None,
            statistics.mean(log_ranks) if log_ranks else None,
            statistics.mean(
                abs(log_ranks[i + 1] - 2 * log_ranks[i] + log_ranks[i - 1])
                for i in range(1, len(log_ranks) - 1)
            )
            if len(log_ranks) > 2
            else None,
        ]
