"""Independent 128-permutation MinHash and LSH document candidate retrieval."""

import random
from collections import defaultdict

from backend.app.engines.plagiarism.winnowing import stable_hash, tokens

PRIME = (1 << 61) - 1


class MinHashLSH:
    def __init__(self, permutations=128, bands=16, rows=8, shingle_size=5):
        if bands * rows != permutations or min(permutations, bands, rows, shingle_size) < 1:
            raise ValueError("Invalid LSH configuration")
        self.permutations, self.bands, self.rows, self.k = permutations, bands, rows, shingle_size
        rng = random.Random(42)
        self.coefficients = [
            (rng.randrange(1, PRIME), rng.randrange(PRIME)) for _ in range(permutations)
        ]
        self.buckets = defaultdict(set)
        self.signatures = {}

    def signature(self, text: str) -> tuple[int, ...] | None:
        words = [word.text for word in tokens(text)]
        shingles = {
            stable_hash("\x1f".join(words[i : i + self.k])) % PRIME
            for i in range(len(words) - self.k + 1)
        }
        if not shingles:
            return None  # Empty documents must not match one another.
        return tuple(
            min((a * value + b) % PRIME for value in shingles) for a, b in self.coefficients
        )

    def add(self, identifier: str, text: str):
        signature = self.signature(text)
        if signature is None:
            return
        self.signatures[identifier] = signature
        for band in range(self.bands):
            key = (band, signature[band * self.rows : (band + 1) * self.rows])
            self.buckets[key].add(identifier)

    def query(self, text: str) -> dict[str, float]:
        signature = self.signature(text)
        if signature is None:
            return {}
        candidates = set()
        for band in range(self.bands):
            candidates.update(
                self.buckets.get((band, signature[band * self.rows : (band + 1) * self.rows]), ())
            )
        return {
            key: sum(a == b for a, b in zip(signature, self.signatures[key], strict=True))
            / self.permutations
            for key in candidates
        }
