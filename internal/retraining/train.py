"""Train tiny logistic heads from genuine labeled, grouped per-segment score JSONL."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from product.engine.calibration import sigmoid


def read_data(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    groups, ids = {}, set()
    for row in rows:
        if not all(row.get(k) for k in ["id", "group", "task", "signature", "provenance"]):
            raise ValueError("Missing identity or provenance")
        if row["id"] in ids or row["split"] not in {"train", "validation", "test"} or type(row["label"]) is not int or row["label"] not in {0, 1}:
            raise ValueError("Invalid labels, split or duplicate identity")
        ids.add(row["id"])
        key = row["group"]
        if key in groups and groups[key] != row["split"]:
            raise ValueError("A source/topic group leaks between splits")
        groups[key] = row["split"]
        features = row["features"]
        if not isinstance(features, dict) or not features or any(type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1 for v in features.values()):
            raise ValueError("Features must be normalized finite signal scores")
    return rows


def metrics(rows, names, weights, bias):
    probabilities = [sigmoid(bias + sum(row["features"][n] * w for n, w in zip(names, weights, strict=True))) for row in rows]
    labels = [row["label"] for row in rows]
    human = [p for p, label in zip(probabilities, labels, strict=True) if label == 0]
    return {"count": len(rows), "accuracy_at_0_5": sum(int(p >= .5) == y for p, y in zip(probabilities, labels, strict=True)) / len(rows), "brier": sum((p - y) ** 2 for p, y in zip(probabilities, labels, strict=True)) / len(rows), "human_false_positive_rate_at_0_5": sum(p >= .5 for p in human) / len(human)}


def train(rows, steps=3000, rate=0.15):
    tasks = sorted({row["task"] for row in rows})
    heads = {}
    for task in tasks:
        selected = [row for row in rows if row["task"] == task]
        signatures = {row["signature"] for row in selected}
        names = sorted(selected[0]["features"])
        if len(signatures) != 1 or any(sorted(row["features"]) != names for row in selected):
            raise ValueError("A head requires exactly one signal signature/feature schema")
        splits = {split: [row for row in selected if row["split"] == split] for split in ["train", "validation", "test"]}
        for values in splits.values():
            if len(values) < 10 or {row["label"] for row in values} != {0, 1}:
                raise ValueError("Each split needs at least 10 real labeled rows, with both classes")
        if task not in {"ai_text", "ai_code", "plagiarism"}:
            raise ValueError("Unsupported task")
        weights, bias = [0.0] * len(names), 0.0
        fitting = splits["train"]
        # Full-batch penalized maximum likelihood. Test labels never affect fitting/selection.
        for _ in range(steps):
            gradients, bias_gradient = [0.0] * len(names), 0.0
            for row in fitting:
                features = [row["features"][name] for name in names]
                delta = sigmoid(bias + sum(v * w for v, w in zip(features, weights, strict=True))) - row["label"]
                bias_gradient += delta
                gradients = [g + delta * v for g, v in zip(gradients, features, strict=True)]
            bias -= rate * bias_gradient / len(fitting)
            weights = [w - rate * (g / len(fitting) + 0.001 * w) for w, g in zip(weights, gradients, strict=True)]
        heads[task] = {"status": "fitted", "production_approved": False, "signature": next(iter(signatures)), "features": names, "weights": weights, "bias": bias, "training_count": len(fitting), "validation": metrics(splits["validation"], names, weights, bias), "test": metrics(splits["test"], names, weights, bias)}
    return {"schema_version": 1, "status": "fitted", "heads": heads, "claim_allowed": False}


def main():
    parser = argparse.ArgumentParser(description="Fit internal logistic calibration heads")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new output file; existing weights are not overwritten")
    artifact = train(read_data(args.data))
    artifact["dataset_sha256"] = hashlib.sha256(args.data.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    print(json.dumps({task: head["test"] for task, head in artifact["heads"].items()}, indent=2))


if __name__ == "__main__":
    main()
