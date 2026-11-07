"""Reproducible labeled copying-vs-independent pairs; development validation only."""
import argparse
import json
from pathlib import Path

from product.engine.similarity import lexical


def records():
    output = []
    # Author-generated templates, controlled interventions; not AI-authorship training.
    for i in range(90):
        source = f"Field station {i} measured rainfall near river basin {i + 130} during the spring survey. Researchers logged the daily water level and recorded soil moisture in a numbered notebook."
        independent = f"In district {i + 400}, a community orchestra rehearsed new music for its autumn concert. Volunteer performers arranged the stage and invited local families to attend the evening event."
        variants = [(source, 1), (source.replace("Researchers", "The field researchers").replace("daily", "average daily"), 1), (independent, 0), ("The project considered rainfall and soil, but the report contains no field measurements or station observations from this survey.", 0)]
        split = "train" if i < 60 else "validation" if i < 75 else "test"
        for j, (query, label) in enumerate(variants):
            value = lexical(query, source)
            output.append({"id": f"pair-{i}-{j}", "group": f"topic-{i}", "task": "plagiarism", "split": split, "label": label, "signature": "lexical-v1", "provenance": "first-party controlled copy/independent intervention; template-domain development data", "features": {"lexical": value, "semantic": 0.0, "ensemble": value}})
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output must be new")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row) + "\n" for row in records()))


if __name__ == "__main__":
    main()
