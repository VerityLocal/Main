"""End-to-end parsing and comparison; fixture source retrieval or explicit live web."""
import argparse
import json
from pathlib import Path

from product.engine.server import DEFAULT_CONFIG
from product.engine.detection import DetectionEngine
from product.engine.pdf import extract_pdf
from product.tests.browser.make_pdfs import BASE, SOURCE_TEXT, main as make_fixtures


class FixtureSources:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def search(self, query):
        # Only retrieval is deterministic here; similarity/segmentation are real.
        return [{"url": "https://example.org/rain-garden-demo", "title": "Controlled demo reference", "text": SOURCE_TEXT}], True


def main():
    make_fixtures()
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicit consent to send example excerpts to live search")
    parser.add_argument("--pdf", type=Path, default=BASE / "pdfs/source-overlap.pdf")
    parser.add_argument("--max-queries", type=int, help="Bound demo query count (1 to 64)")
    parser.add_argument("--output", type=Path, help="Save a new demo result file")
    args = parser.parse_args()
    if args.max_queries is not None and not 1 <= args.max_queries <= 64:
        parser.error("--max-queries must be between 1 and 64")
    if args.output and args.output.exists():
        parser.error("Choose a new output file; existing reports are not overwritten")
    snapshot = extract_pdf(args.pdf.read_bytes())
    config = json.loads(DEFAULT_CONFIG.read_text()) if DEFAULT_CONFIG.exists() else {}
    if args.max_queries is not None:
        config["max_queries"] = args.max_queries
    engine = DetectionEngine(config, source_factory=None if args.live else FixtureSources)
    result = engine.run(snapshot["text"], consent=True)
    output = json.dumps({"mode": "live-web" if args.live else "controlled-reference-fixture", "overall": result["overall"], "segments": [{"text": row["text"], "ai_status": row["ai"]["status"], "source_status": row["plagiarism"]["status"], "similarity": row["plagiarism"]["score"], "source": row["plagiarism"]["match"]["url"] if row["plagiarism"]["match"] else None} for row in result["segments"]]}, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
