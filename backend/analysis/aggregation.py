"""Flagged token share and raw arithmetic mean are different, explicitly labeled metrics."""

import math


def aggregate(scored: list[dict], threshold: float) -> dict:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Invalid threshold")
    for item in scored:
        if (not math.isfinite(item["probability"]) or not 0 <= item["probability"] <= 1
                or type(item["content_tokens"]) is not int or item["content_tokens"] <= 0):
            raise ValueError("Invalid scored chunk; aggregation would be misleading")
    if not scored:
        return {"flagged_content_share": None, "raw_mean_model_score": None, "signal_band": None,
                "analyzed_tokens": 0, "analyzed_chunks": 0, "flagged_passages": []}
    total = sum(item["content_tokens"] for item in scored)
    flagged = [item for item in scored if item["probability"] > threshold]
    share = sum(item["content_tokens"] for item in flagged)/total
    return {
        "flagged_content_share": share,
        "raw_mean_model_score": sum(item["probability"] for item in scored)/len(scored),
        "signal_band": "low" if share < .2 else "moderate" if share < .5 else "high",
        "signal_band_note": "Heuristic detector-signal bands, not calibrated authorship verdicts.",
        "analyzed_tokens": total, "analyzed_chunks": len(scored), "flagged_passages": flagged,
    }
