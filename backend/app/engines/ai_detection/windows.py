"""Tokenizer overflow windows; reconstruct unique source-token coverage."""

import torch

from backend.app.document.chunking import sentence_spans
from backend.app.document.offsets import Utf16Index
from backend.app.engines.stylometry.normalization import normalize


def window_batches(text, tokenizer, feature_result, normalizer, length=512, stride=96):
    if not tokenizer.is_fast:
        raise ValueError("A fast tokenizer is required for original offsets")
    sentences = sentence_spans(text)
    if len(sentences) > 128:
        raise ValueError("This profile supports at most 128 sentences; no silent truncation")
    encoding = tokenizer(
        text,
        max_length=length,
        stride=stride,
        truncation=True,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )
    index = Utf16Index(text)
    features, masks = (
        zip(
            *(normalize(row["features"], normalizer) for row in feature_result["sentences"]),
            strict=True,
        )
        if sentences
        else ((), ())
    )
    seen = set()
    for ids, attention, offsets in zip(
        encoding["input_ids"], encoding["attention_mask"], encoding["offset_mapping"], strict=True
    ):
        spans = [
            [
                bool(end > start and start < sentence.end_cp and end > sentence.start_cp)
                for start, end in offsets
            ]
            for sentence in sentences
        ]
        coverage = []
        for mask in spans:
            unique = set(
                (start, end) for active, (start, end) in zip(mask, offsets, strict=True) if active
            )
            fresh = unique - seen
            coverage.append(
                float(sum(index.to_utf16(end) - index.to_utf16(start) for start, end in fresh))
            )
        seen.update((start, end) for start, end in offsets if end > start)
        yield (
            {
                "input_ids": torch.tensor([ids]),
                "attention_mask": torch.tensor([attention]),
                "sentence_token_mask": torch.tensor([spans], dtype=torch.bool),
                "features": torch.tensor([features], dtype=torch.float32),
                "feature_valid_mask": torch.tensor([masks], dtype=torch.bool),
            },
            torch.tensor(coverage),
        )
