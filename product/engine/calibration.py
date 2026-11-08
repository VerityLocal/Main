"""Real, signature-bound logistic calibration. Missing heads never become probabilities."""
import json
import math
from pathlib import Path


def sigmoid(value):
    return 1 / (1 + math.exp(-max(-40, min(40, value))))


class Calibration:
    def __init__(self, path=None, allow_development=False):
        path = path or Path(__file__).with_name("calibration.json")
        self.artifact = json.loads(Path(path).read_text())
        self.allow_development = allow_development
        if self.artifact.get("schema_version") != 1:
            raise ValueError("Invalid calibration artifact")

    def predict(self, task, features, signature):
        head = self.artifact.get("heads", {}).get(task)
        if not head or head.get("signature") != signature or head.get("status") != "fitted":
            return None
        if not self.allow_development and not head.get("production_approved", False):
            return None
        names = head["features"]
        if any(name not in features or not math.isfinite(features[name]) for name in names):
            return None
        weights = head["weights"]
        if len(names) != len(weights) or not all(math.isfinite(x) for x in weights + [head["bias"]]):
            return None
        return sigmoid(head["bias"] + sum(features[n] * w for n, w in zip(names, weights, strict=True)))
