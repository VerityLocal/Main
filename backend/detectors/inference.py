"""Small, already-segmented input scoring; no PDF extraction or document chunker."""

from dataclasses import dataclass, field
from threading import Lock
from typing import Any


def masked_mean(hidden_states: Any, attention_mask: Any) -> Any:
    mask = attention_mask.unsqueeze(-1).to(hidden_states.dtype)
    return (hidden_states * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)


@dataclass(frozen=True)
class ChunkScore:
    probability: float
    input_tokens: int  # Includes special tokens, excludes padding.


@dataclass
class LoadedDetector:
    kind: str
    tokenizer: Any
    model: Any
    device: str
    max_tokens: int
    batch_size: int
    _lock: Lock = field(default_factory=Lock, repr=False)

    def predict_chunks(self, inputs: list[str]) -> list[ChunkScore]:
        """Return unrounded sigmoid scores; reject oversize chunks rather than truncate.

        Does not strip/normalize source, classify its language, or establish that
        content is long enough for reliable detection. Those are pipeline tasks.
        """
        import torch

        if not isinstance(inputs, list):
            raise ValueError("Inputs must be a list of text chunks")
        if not inputs:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in inputs):
            raise ValueError("Every chunk must contain non-whitespace text")
        with self._lock:
            encoded = self.tokenizer(
                inputs, add_special_tokens=True, truncation=False,
                padding=False, return_attention_mask=True, verbose=False,
            )
            lengths = [len(ids) for ids in encoded["input_ids"]]
            if any(length > self.max_tokens for length in lengths):
                raise ValueError(f"Chunk exceeds the {self.max_tokens}-token budget; split it first")
            scores = []
            with torch.inference_mode():
                for start in range(0, len(inputs), self.batch_size):
                    rows = [
                        {key: values[i] for key, values in encoded.items()}
                        for i in range(start, min(start + self.batch_size, len(inputs)))
                    ]
                    batch = self.tokenizer.pad(rows, padding=True, return_tensors="pt")
                    batch = {key: value.to(self.device) for key, value in batch.items()}
                    logits = self.model(**batch).reshape(-1)
                    if logits.numel() != len(rows) or not torch.isfinite(logits).all():
                        raise RuntimeError("Detector returned invalid logits; no scores are available")
                    probabilities = torch.sigmoid(logits).cpu().tolist()
                    scores.extend(
                        ChunkScore(probability, lengths[start + i])
                        for i, probability in enumerate(probabilities)
                    )
            return scores
