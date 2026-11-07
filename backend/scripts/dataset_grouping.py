"""Deterministic exact/near-duplicate grouping before any split or sampling."""

import hashlib
import heapq
import math
import re
import unicodedata
from array import array
from bisect import bisect_left
from collections import Counter


class Components:
    def __init__(self, size):
        self.parents = list(range(size))

    def find(self, item):
        while self.parents[item] != item:
            self.parents[item] = self.parents[self.parents[item]]
            item = self.parents[item]
        return item

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left == right:
            return False
        self.parents[max(left, right)] = min(left, right)
        return True


def normalized_digest(text):
    return hashlib.sha256(" ".join(text.casefold().split()).encode("utf-8")).hexdigest()


def shingle_hashes(text, width=5):
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
    if not words:
        return array("Q")
    width = min(width, len(words))
    values = {
        int.from_bytes(
            hashlib.blake2b("\x1f".join(words[i : i + width]).encode(), digest_size=8).digest(),
            "little",
        )
        for i in range(len(words) - width + 1)
    }
    return array("Q", sorted(values))


def near_duplicate_components(shingles, components, threshold_percent=85, progress=lambda _: None):
    """Prefix-filtered Jaccard join, with exact candidate verification.

    Unlike probabilistic LSH retrieval, prefix filtering visits every qualifying
    pair in the hashed-shingle space. Persisted shingles/postings are compact arrays.
    """
    if not 1 <= threshold_percent <= 100:
        raise ValueError("Jaccard threshold must be between 1 and 100 percent")
    frequencies = Counter(value for values in shingles for value in values)
    order = sorted(range(len(shingles)), key=lambda i: (len(shingles[i]), i))
    lengths = [len(shingles[i]) for i in order]
    postings = {}
    candidates_checked = edges = 0
    for position, identifier in enumerate(order):
        values = shingles[identifier]
        size = len(values)
        if not size:
            continue
        minimum = math.ceil(threshold_percent * size / 100)
        prefix = heapq.nsmallest(
            size - minimum + 1, values, key=lambda value: (frequencies[value], value)
        )
        earliest = bisect_left(lengths, minimum, hi=position)
        candidates = set()
        for value in prefix:
            previous = postings.get(value, ())
            candidates.update(previous[bisect_left(previous, earliest) :])
        current_set = None
        for candidate in sorted(candidates):
            other = order[candidate]
            if components.find(identifier) == components.find(other):
                continue
            if current_set is None:
                current_set = set(values)
            candidates_checked += 1
            overlap = sum(value in current_set for value in shingles[other])
            union_size = size + lengths[candidate] - overlap
            if 100 * overlap >= threshold_percent * union_size:
                edges += int(components.union(identifier, other))
        for value in prefix:
            if value not in postings:
                postings[value] = array("I")
            postings[value].append(position)
        if (position + 1) % 5000 == 0:
            progress(
                {"grouped_records": position + 1, "candidate_pairs_checked": candidates_checked}
            )
    return {"candidate_pairs_checked": candidates_checked, "near_duplicate_component_merges": edges}


def group_records(records, progress=lambda _: None):
    components = Components(len(records))
    topics, exact = {}, {}
    topic_edges = exact_edges = 0
    for i, row in enumerate(records):
        topic = row["topic_id"]
        if topic in topics:
            topic_edges += int(components.union(i, topics[topic]))
        topics[topic] = i
        digest = normalized_digest(row["text"])
        if digest in exact:
            exact_edges += int(components.union(i, exact[digest]))
        exact[digest] = i
    progress({"stage": "hashing_near_duplicate_shingles", "records": len(records)})
    shingles = [shingle_hashes(row["text"]) for row in records]
    stats = near_duplicate_components(shingles, components, progress=progress)
    roots = [components.find(i) for i in range(len(records))]
    return roots, {
        **stats,
        "method": "deterministic_prefix_join_exact_hashed_shingle_jaccard",
        "normalization": "NFKC_casefold_unicode_word_tokens",
        "shingle_words": 5,
        "hash": "blake2b_64",
        "jaccard_threshold": 0.85,
        "records_audited": len(records),
        "topic_groups": len(topics),
        "topic_component_merges": topic_edges,
        "exact_normalized_component_merges": exact_edges,
        "components": len(set(roots)),
        "largest_component_records": max(Counter(roots).values(), default=0),
        "limitations": [
            "Unavailable original author/source IDs cannot be reconstructed from topic IDs",
            "Paraphrases below the declared lexical similarity threshold are not identified",
            "The join uses 64-bit shingle hashes; collisions are theoretically possible",
        ],
    }
