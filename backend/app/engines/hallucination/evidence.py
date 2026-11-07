"""Four-state aggregation across sources; neutral is not contradiction."""


def aggregate(evidence, threshold=0.85):
    # This is a proposed threshold, not validation-fitted calibration.
    supports, contradicts = set(), set()
    for item in evidence:
        if item.get("reliability") != "user_trusted":
            continue
        scores = item.get("nli") or {}
        if scores.get("entailment", 0) >= threshold:
            supports.add(item["source_id"])
        if scores.get("contradiction", 0) >= threshold:
            contradicts.add(item["source_id"])
    if any(left != right for left in supports for right in contradicts):
        return "CONFLICTING_EVIDENCE"
    if supports and contradicts:
        return "INSUFFICIENT_EVIDENCE"
    if supports:
        return "SUPPORTED"
    if contradicts:
        return "CONTRADICTED"
    return "INSUFFICIENT_EVIDENCE"
