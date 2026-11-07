"""Metrics calculated only from supplied labels; unsupported strata are null."""


def classification_summary(labels, probabilities):
    import math

    if (
        not labels
        or len(labels) != len(probabilities)
        or not set(labels) <= {0, 1}
        or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)
    ):
        raise ValueError("Metrics require matched binary labels and finite probabilities")
    tn = fp = fn = tp = 0
    for label, probability in zip(labels, probabilities, strict=True):
        prediction = int(probability >= 0.5)
        tn += int(label == prediction == 0)
        tp += int(label == prediction == 1)
        fp += int(label == 0 and prediction == 1)
        fn += int(label == 1 and prediction == 0)
    return {
        "records": len(labels),
        "accuracy_at_0_5": (tn + tp) / len(labels),
        "human_false_positive_rate_at_0_5": fp / (tn + fp) if tn + fp else None,
        "ai_recall_at_0_5": tp / (tp + fn) if tp + fn else None,
        "confusion_matrix_at_0_5": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def binary_metrics(labels, probabilities, bins=15):
    from sklearn.metrics import precision_recall_fscore_support, roc_auc_score, roc_curve

    if not labels or len(labels) != len(probabilities) or set(labels) != {0, 1}:
        raise ValueError("Binary metrics require matched labels and both classes")
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        [int(p >= 0.5) for p in probabilities],
        average="macro",
        zero_division=0,
    )
    fpr, tpr, _ = roc_curve(labels, probabilities)
    ece = 0.0
    for i in range(bins):
        selected = [
            j
            for j, p in enumerate(probabilities)
            if i / bins <= p < (i + 1) / bins or (i == bins - 1 and p == 1)
        ]
        if selected:
            gap = abs(
                sum(labels[j] for j in selected) / len(selected)
                - sum(probabilities[j] for j in selected) / len(selected)
            )
            ece += len(selected) / len(labels) * gap
    return {
        **classification_summary(labels, probabilities),
        "macro_precision": float(precision),
        "macro_recall": float(recall),
        "macro_f1": float(f1),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "tpr_at_fpr_0_01": float(max(tpr[fpr <= 0.01], default=0)),
        "tpr_at_fpr_0_001": float(max(tpr[fpr <= 0.001], default=0)),
        "low_fpr_small_sample_caution": labels.count(0) < 1000,
        "ece_ai_probability_equal_width_15_bins": ece,
        "brier": sum((p - y) ** 2 for p, y in zip(probabilities, labels, strict=True))
        / len(labels),
    }
