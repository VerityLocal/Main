"""Measured CPU pipeline timing; synthetic fixtures are labeled, never accuracy."""

import argparse
import json
import statistics
import time
from pathlib import Path

import psutil

from backend.app.core.config import Settings, load_platform_config
from backend.app.document.builder import build_document
from backend.app.engines.hallucination.inference import analyze as claims
from backend.app.engines.plagiarism.inference import analyze as similarity
from backend.app.engines.stylometry.extractor import FeatureExtractor
from backend.app.runtime.inference_queue import AnalysisContext
from backend.app.runtime.profiling import profile_hardware
from backend.app.schemas.analysis import Source
from backend.app.services.model_manager import ModelManager


def main():
    parser = argparse.ArgumentParser(
        description="Bounded CPU pipeline timing, not accuracy or model-fit proof"
    )
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--text", type=Path)
    parser.add_argument("--sources", type=Path, help="JSON array of Source objects")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.runs <= 10:
        raise SystemExit("Output must be new and runs between 1 and 10")
    if args.synthetic:
        text = (
            "😀 Alice visited Paris during the summer of 2024. "
            "Water freezes at zero degrees Celsius."
        )
        sources = [Source(source_id="synthetic_source", title="Synthetic fixture", text=text)]
    elif args.text and args.sources:
        text = args.text.read_text(encoding="utf-8")
        sources = [
            Source.model_validate_json(json.dumps(s))
            for s in json.loads(args.sources.read_text(encoding="utf-8"))
        ]
    else:
        raise SystemExit("Choose --synthetic or supply --text and --sources")
    if len(text) > 20_000 or len(sources) > 256 or sum(len(s.text) for s in sources) > 2_000_000:
        raise SystemExit("Benchmark input exceeds the runtime corpus/document bounds")
    settings = Settings()
    config = load_platform_config(settings.config_dir)
    models = ModelManager(settings, config)
    document = build_document([text])
    functions = {
        "similarity": lambda c: similarity(document, sources, models, config, c),
        "claims": lambda c: claims(document, sources, models, config, c, lambda payload: None),
        "light_features_without_detector_tokenizer": lambda c: FeatureExtractor().extract(text),
    }
    report = {
        "synthetic_fixture_not_accuracy": args.synthetic,
        "hardware": profile_hardware(3).model_dump(mode="json"),
        "document_code_points": len(text),
        "sources": len(sources),
        "models": models.status(),
        "benchmarks": {},
        "rss_policy": "before_after_observation_not_sampled_peak_or_fit_guarantee",
    }
    process = psutil.Process()
    for name, function in functions.items():
        durations = []
        before = process.memory_info().rss
        started = time.perf_counter()
        function(AnalysisContext(time.monotonic() + 180))
        cold_ms = (time.perf_counter() - started) * 1000
        for _ in range(args.runs):
            started = time.perf_counter()
            function(AnalysisContext(time.monotonic() + 180))
            durations.append((time.perf_counter() - started) * 1000)
        report["benchmarks"][name] = {
            "first_call_ms": cold_ms,
            "repeat_ms": durations,
            "median_repeat_ms": statistics.median(durations),
            "rss_before_bytes": before,
            "rss_after_bytes": process.memory_info().rss,
        }
    models.unload()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print("Measured CPU timings written; no accuracy or full-model/GPU-fit claim.")


if __name__ == "__main__":
    main()
