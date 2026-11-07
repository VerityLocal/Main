"""Fit using valid training entries only; persist exact profile and resources."""

import math


def fit_normalizer(rows):
    columns = [[row[i] for row in rows if row[i] is not None] for i in range(24)]
    means = [sum(column) / len(column) if column else 0.0 for column in columns]
    scales = [
        math.sqrt(sum((x - mean) ** 2 for x in column) / len(column)) if column else 1.0
        for column, mean in zip(columns, means, strict=True)
    ]
    return {
        "means": means,
        "scales": [value or 1.0 for value in scales],
        "valid_counts": list(map(len, columns)),
    }


def normalize(features, statistics):
    if len(features) != 24:
        raise ValueError("Feature schema mismatch")
    values = []
    for i, value in enumerate(features):
        if value is not None and statistics["valid_counts"][i] == 0:
            raise ValueError("Runtime feature was never valid in training")
        values.append(
            (value - statistics["means"][i]) / statistics["scales"][i] if value is not None else 0.0
        )
    return values, [value is not None for value in features]
