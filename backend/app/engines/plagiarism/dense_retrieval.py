"""BGE token windows and a per-analysis cached corpus matrix; CPU only."""

import importlib.util

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class DenseRetriever:
    def __init__(self, models, check=lambda: None):
        self.models, self.check = models, check
        self.cached_passages = None
        self.matrix = None
        self.index = None
        self.window_count = 0

    def encode(self, texts, *, query=False):
        import numpy as np

        if not texts:
            return None
        vectors = []
        with self.models.lease("dense_retriever") as bundle:
            tokenizer = bundle.model.tokenizer
            if not tokenizer.is_fast:
                raise ValueError("Dense window coverage requires a fast tokenizer")
            prefix = QUERY_PREFIX if query else ""
            budget = bundle.model.max_seq_length - len(tokenizer.encode(prefix)) - 4
            if budget < 32:
                raise ValueError("Dense token budget is too small")
            step = max(1, budget - 32)
            for text in texts:
                self.check()
                offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)[
                    "offset_mapping"
                ]
                chunks, weights = [], []
                covered = 0
                for first in range(0, len(offsets), step):
                    last = min(first + budget, len(offsets))
                    start, end = offsets[first][0], offsets[last - 1][1]
                    chunks.append(prefix + text[start:end])
                    weights.append(last - max(first, covered))
                    covered = last
                    if last == len(offsets):
                        break
                if not chunks:
                    chunks, weights = [prefix + text], [1]
                window_vectors = []
                for chunk in chunks:
                    self.check()
                    # Refuse unexpected tokenizer changes rather than truncating.
                    if len(tokenizer.encode(chunk)) > bundle.model.max_seq_length:
                        raise ValueError("Dense window exceeded its explicit token budget")
                    window_vectors.append(
                        bundle.model.encode(
                            [chunk],
                            batch_size=1,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                        )[0]
                    )
                    self.window_count += 1
                pooled = np.average(window_vectors, axis=0, weights=weights)
                vectors.append(pooled / max(float(np.linalg.norm(pooled)), 1e-12))
        return np.asarray(vectors, dtype="float32")

    def search(self, query, passages, k=8):
        k = min(k, len(passages))
        if not k:
            return [], "empty"
        identity = tuple(passages)
        if self.cached_passages != identity:
            self.matrix = self.encode(passages)
            self.cached_passages = identity
            self.index = None
            if importlib.util.find_spec("faiss"):
                import faiss

                self.index = faiss.IndexFlatIP(self.matrix.shape[1])
                self.index.add(self.matrix)
        vector = self.encode([query], query=True)
        if self.index is not None:
            scores, indices = self.index.search(vector, k)
            return [(int(i), float(s)) for i, s in zip(indices[0], scores[0], strict=True)], (
                "faiss_flat_ip"
            )
        scores = (self.matrix @ vector[0]).tolist()
        return sorted(enumerate(scores), key=lambda item: (-item[1], item[0]))[:k], (
            "numpy_exact_cosine"
        )
