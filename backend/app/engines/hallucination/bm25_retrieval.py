"""BM25 lexical ranking over original-offset passages."""

import math
from collections import Counter

from backend.app.engines.plagiarism.winnowing import tokens


class BM25:
    def __init__(self, texts: list[str], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.documents = [Counter(t.text for t in tokens(text)) for text in texts]
        self.lengths = [sum(doc.values()) for doc in self.documents]
        self.average = sum(self.lengths) / len(texts) if texts else 1
        self.df = Counter(term for doc in self.documents for term in doc)

    def search(self, query: str, k=8):
        scores = []
        n = len(self.documents)
        for i, doc in enumerate(self.documents):
            value = 0.0
            for term in {t.text for t in tokens(query)}:
                frequency = doc[term]
                if not frequency:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                value += (
                    idf
                    * frequency
                    * (self.k1 + 1)
                    / (
                        frequency
                        + self.k1 * (1 - self.b + self.b * self.lengths[i] / max(self.average, 1))
                    )
                )
            if value > 0:
                scores.append((i, value))
        return sorted(scores, key=lambda item: (-item[1], item[0]))[:k]
