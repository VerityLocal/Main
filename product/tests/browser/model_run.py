"""Explicit genuine offline model smoke; no synthetic weights or accuracy claims."""
import argparse
import json
import math
import sys
import time
from pathlib import Path

from product.engine.server import DEFAULT_CONFIG  # Establish offline policy first.
from product.engine.ai import AIClassifier, RatioSignal
from product.engine.assets import verify_assets
from product.engine.calibration import Calibration
from product.engine.detection import DetectionEngine
from product.engine.resources import ResourceLimit, physical_memory
from product.engine.similarity import Semantic
from product.engine.text import words
from product.tests.browser.make_pdfs import SOURCE_TEXT
from product.tests.browser.run import FixtureSources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Write a new functional-validation report, not raw model scores")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Choose a new output file; existing reports are not overwritten")
    profile = json.loads(args.profile.read_text())
    text_config = profile["signals"]["text"]
    semantic_config = profile["semantic"]
    verify_assets(text_config, ("path",))
    verify_assets(semantic_config, ("path",))
    # Limit CPU parallelism for an interactive companion on a laptop.
    import torch
    torch.set_num_threads(min(4, torch.get_num_threads()))
    classifier = AIClassifier({"text": text_config}, Calibration())
    row = {"kind": "text", "text": SOURCE_TEXT, "words": len(words(SOURCE_TEXT))}
    started = time.monotonic()
    values, signature = classifier.features(row)
    text_seconds = time.monotonic() - started
    assert classifier.states["text"] == "feature_computed", classifier.states
    assert "text" in values and math.isfinite(values["text"]) and signature
    score = classifier.score(row)
    assert score["status"] == "calibration_required" and score["score"] is None and score["confidence"] is None, score
    assert classifier.signals[0][1].score("word " * 800) is None, "long prose must abstain, not truncate"
    semantic = Semantic(semantic_config)
    started = time.monotonic()
    identical = semantic.score(SOURCE_TEXT, SOURCE_TEXT)
    related = semantic.score(SOURCE_TEXT, "Rain gardens absorb stormwater and help manage runoff in urban neighborhoods.")
    semantic_seconds = time.monotonic() - started
    assert identical is not None and 0.99 <= identical <= 1
    assert related is not None and math.isfinite(related) and 0 <= related <= 1
    assert semantic.score("word " * 600, SOURCE_TEXT) is None, "long semantic inputs must abstain"
    # Actual PDF/source comparison remains evidence, even with both genuine models.
    engine = DetectionEngine({"semantic": semantic_config}, classifier=classifier, source_factory=FixtureSources)
    engine.semantic = semantic
    result = engine.run(SOURCE_TEXT, consent=True)
    assert result["overall"]["ai"]["percent"] is None
    assert all(item["ai"]["status"] == "calibration_required" for item in result["segments"])
    assert any(item["plagiarism"]["match"] for item in result["segments"])
    ratio_status = "not_executed; full-pair acceptance requires a capable workstation"
    if physical_memory() < 64 * 1024 ** 3:
        try:
            RatioSignal({}).score(SOURCE_TEXT)
        except ResourceLimit:
            ratio_status = "actual physical-memory abstention passed; no weights opened"
        else:
            raise AssertionError("full Falcon pair was not resource-gated")
    report = {"kind": "functional_smoke_not_accuracy_benchmark", "offline_inference": "passed; local-only loaders with hash-verified assets", "desklib": "genuine trained head produced finite internal feature", "desklib_cold_seconds": round(text_seconds, 3), "semantic": "genuine BGE identical/related inference passed", "semantic_cold_seconds": round(semantic_seconds, 3), "oversize_inputs": "abstained without silent truncation", "document_ai_percentage": "unavailable; independent calibration required", "source_match": "controlled reference with genuine semantic inference", "binoculars": ratio_status, "gptsniffer": "not executed; permitted trained checkpoint required", "samecode_production_corpus": "not supplied; development-fixture match tested separately", "physical_ram_gib": round(physical_memory() / 1024 ** 3, 2)}
    if sys.platform != "win32":
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["process_peak_rss_gib"] = round(peak / (1024 ** 3 if sys.platform == "darwin" else 1024 ** 2), 3)
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(output)
    print(output)


if __name__ == "__main__":
    main()
