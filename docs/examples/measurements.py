def summarize_readings(readings):
    # Retain numeric observations in their original order.
    valid = []
    for reading in readings:
        if isinstance(reading, (int, float)):
            valid.append(reading)
    if not valid:
        return {"count": 0, "average": None}
    total = sum(valid)
    average = total / len(valid)
    return {"count": len(valid), "average": average}


def measurement_spread(readings):
    valid = [value for value in readings
             if isinstance(value, (int, float))]
    if len(valid) < 2:
        return 0
    smallest = min(valid)
    largest = max(valid)
    return largest - smallest


def compare_trials(first_trial, second_trial):
    first = summarize_readings(first_trial)
    second = summarize_readings(second_trial)
    if not first["count"] or not second["count"]:
        return None
    return second["average"] - first["average"]
