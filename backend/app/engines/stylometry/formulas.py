"""Document-context lexical statistics; invalid values are None, never zero."""

import math
import statistics
from collections import Counter


def entropy(counts):
    total = sum(counts)
    if total < 2:
        return None
    return -sum((count / total) * math.log2(count / total) for count in counts if count)


def mattr(words, window=50):
    if len(words) < window:
        return None
    counter = Counter(words[:window])
    total = len(counter) / window
    for i in range(window, len(words)):
        old = words[i - window]
        counter[old] -= 1
        if not counter[old]:
            del counter[old]
        counter[words[i]] += 1
        total += len(counter) / window
    return total / (len(words) - window + 1)


def richness(words):
    n, counts = len(words), Counter(words)
    if n < 50:
        return None, None
    yule = 10000 * (sum(value * value for value in counts.values()) - n) / (n * n)
    singleton = sum(value == 1 for value in counts.values())
    honore = 100 * math.log(n) / (1 - singleton / len(counts)) if singleton != len(counts) else None
    return yule, honore


def burstiness(lengths):
    return (
        statistics.pstdev(lengths) / statistics.mean(lengths)
        if len(lengths) > 1 and sum(lengths) > 0
        else None
    )
