"""The only public analysis engine interface; independent AI/web failure semantics."""
import asyncio
import hashlib

from .ai import AIClassifier
from .calibration import Calibration
from .similarity import Semantic, compare
from .text import aggregate, segment
from .web import WebSources


class Cancelled(Exception):
    pass


class DetectionEngine:
    def __init__(self, config=None, calibration=None, classifier=None, source_factory=None):
        self.config = config or {}
        self.calibration = calibration or Calibration()
        self.ai = classifier or AIClassifier(self.config.get("signals", {}), self.calibration)
        self.semantic = Semantic(self.config.get("semantic", {}))
        self.source_factory = source_factory or WebSources

    async def analyze(self, text, *, consent=False, source_url=None, cancelled=lambda: False, progress=lambda _: None):
        if not text.strip() or len(text) > 200_000:
            raise ValueError("Readable text is required (limit: 200,000 characters)")
        rows = segment(text)
        if len(rows) > 1500:
            raise ValueError("This document exceeds the 1,500-segment limit")

        def check():
            if cancelled():
                raise Cancelled()

        for i, row in enumerate(rows):
            check()
            row["ai"] = self.ai.score(row)
            row["plagiarism"] = {"status": "not_checked", "score": None, "confidence": None, "match": None}
            progress({"stage": "local", "done": i + 1, "total": len(rows)})
        max_queries = max(1, min(64, self.config.get("max_queries", 24)))
        if consent:
            eligible = [row for row in rows if row["words"] >= 12]
            for row in rows:
                if row["words"] < 12:
                    row["plagiarism"]["status"] = "insufficient_text"
            try:
                async with self.source_factory() as web:
                    cache = {}
                    for i, row in enumerate(eligible[:max_queries]):
                        check()
                        query = " ".join(row["text"].split())[:220]
                        if query not in cache:
                            cache[query] = await web.search(query)
                        sources, complete = cache[query]
                        match = compare(row["text"], sources, self.semantic, self.calibration, source_url)
                        row["plagiarism"] = {"status": "checked" if complete else "partial_sources", "score": match["similarity"] if match else (0.0 if complete else None), "confidence": match["confidence"] if match else None, "match": match}
                        progress({"stage": "sources", "done": i + 1, "total": min(len(eligible), max_queries)})
            except Cancelled:
                raise
            except Exception:
                for row in eligible:
                    if row["plagiarism"]["status"] == "not_checked":
                        row["plagiarism"]["status"] = "unavailable"
        check()
        ai, plagiarism = aggregate(rows, "ai"), aggregate(rows, "plagiarism")
        # A partial-source match is evidence, but not a completed search for coverage purposes.
        checked_words = sum(r["words"] for r in rows if r["plagiarism"]["status"] == "checked")
        total_words = sum(r["words"] for r in rows)
        plagiarism["search_coverage"] = checked_words / total_words if total_words else 0
        ai["status"] = "complete" if ai["coverage"] == 1 else "partial" if ai["coverage"] else "unavailable"
        plagiarism["status"] = "not_checked" if not consent else "complete" if plagiarism["search_coverage"] == 1 else "partial" if plagiarism["coverage"] else "unavailable"
        return {"schema_version": 1, "document_digest": hashlib.sha256(text.encode()).hexdigest(), "text": text, "segments": rows, "overall": {"ai": ai, "plagiarism": plagiarism}, "notes": ["AI-written % is a word-weighted estimate over scored text, not proof of authorship.", "Plagiarism % is source-similarity evidence over checked text, not proof of misconduct.", "Unchecked text is never counted as original. Citations and quotations require human review."]}

    def run(self, text, **options):
        return asyncio.run(self.analyze(text, **options))
