"""Offline extraction of real ensemble scores for externally labeled calibration data."""
import argparse
import json
from pathlib import Path

from product.desktop.config import bundle_root, offline_policy, standard_config
from product.engine.ai import AIClassifier
from product.engine.calibration import Calibration
from product.engine.text import words


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=bundle_root())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output must be new")
    offline_policy(args.bundle)
    config = standard_config(args.bundle)
    classifier = AIClassifier(config.get("signals", {}), Calibration())
    output = []
    for line in args.data.read_text().splitlines():
        row = json.loads(line)
        if row["kind"] not in {"text", "code"} or len(words(row["text"])) < 12:
            raise ValueError("Unsupported input profile")
        features, signature = classifier.features(row)
        if not features:
            raise ValueError("No licensed local signal produced a score; no synthetic fallback")
        output.append({k: row[k] for k in ["id", "group", "split", "label", "provenance"]} | {"task": "ai_" + row["kind"], "features": features, "signature": signature})
    args.output.write_text("".join(json.dumps(row) + "\n" for row in output))


if __name__ == "__main__":
    main()
