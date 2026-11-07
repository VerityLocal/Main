"""Attributed lexical + optional local semantic similarity. No authorship model here."""
from difflib import SequenceMatcher

from .assets import fingerprint, verify_assets
from .resources import require_memory
from .text import segment, words


def lexical(left, right):
    a, b = words(left), words(right)
    if not a or not b:
        return 0.0
    # Query-token coverage is useful when a source passage is longer than the query.
    overlap = sum(m.size for m in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()) / len(a)
    shingles = lambda tokens: {tuple(tokens[i:i + 3]) for i in range(max(0, len(tokens) - 2))}
    aa, bb = shingles(a), shingles(b)
    containment = len(aa & bb) / len(aa) if aa else 0
    return 0.55 * overlap + 0.45 * containment


class Semantic:
    def __init__(self, config):
        self.config, self.model = config, None

    def score(self, left, right):
        if not self.config.get("enabled") or not self.config.get("license_reviewed") or not self.config.get("snapshot_id"):
            return None

        if self.model is None:
            require_memory(max(4, self.config.get("min_ram_gib", 4)), 0.5)
            verify_assets(self.config, ("path",))
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.config["path"], local_files_only=True, trust_remote_code=False, device="cpu")
        # Refuse silent model truncation. Lexical scores remain available.
        if any(len(self.model.tokenizer.encode(s)) > self.model.max_seq_length for s in [left, right]):
            return None
        vectors = self.model.encode([left, right], normalize_embeddings=True)
        return max(0.0, min(1.0, float(vectors[0] @ vectors[1])))


def compare(query, sources, semantic, calibration, excluded_url=None):
    best = None
    for source in sources:
        if source["url"].split("#")[0] == (excluded_url or "").split("#")[0]:
            continue
        passages = segment(source["text"][:60_000], max_chars=1600)
        # Whole sentence + neighboring sentence windows improve sentence/block alignment.
        values = [row["text"] for row in passages]
        values += [passages[i]["text"] + " " + passages[i + 1]["text"] for i in range(len(passages) - 1)]
        ranked = sorted([(lexical(query, value), value) for value in values], reverse=True)[:3]
        for lex, passage in ranked:
            try:
                sem = semantic.score(query, passage)
            except Exception:
                sem = None
            evidence = lex if sem is None else 0.7 * lex + 0.3 * sem
            # Semantic-only high similarity is a related topic, not proof of copying.
            if lex < 0.35 or evidence < 0.72:
                continue
            signature = "lexical-v1" if sem is None else "lexical-v1+" + fingerprint(semantic.config)
            confidence = calibration.predict("plagiarism", {"lexical": lex, "semantic": sem if sem is not None else 0, "ensemble": evidence}, signature)
            match = {"url": source["url"], "title": source.get("title", "Matched source"), "excerpt": passage[:600], "similarity": evidence, "confidence": confidence}
            if best is None or evidence > best["similarity"]:
                best = match
    return best
