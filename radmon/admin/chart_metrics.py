from __future__ import annotations

from collections.abc import Iterable


def status_breakdown(rates: Iterable[float], *, warnlevel: float, alarmlevel: float) -> dict[str, int]:
    result = {"NORMAL": 0, "ALERT": 0, "ALARM": 0}
    for raw in rates:
        value = float(raw)
        if value >= alarmlevel:
            result["ALARM"] += 1
        elif value >= warnlevel:
            result["ALERT"] += 1
        else:
            result["NORMAL"] += 1
    return result


def threshold_progress(rates: Iterable[float], *, alarmlevel: float) -> dict[str, float]:
    values = [float(value) for value in rates]
    if not values:
        return {
            "current_value": 0.0,
            "average_value": 0.0,
            "peak_value": 0.0,
            "current_percent": 0.0,
            "average_percent": 0.0,
            "peak_percent": 0.0,
        }
    current = values[-1]
    average = sum(values) / len(values)
    peak = max(values)
    scale = float(alarmlevel) if alarmlevel > 0 else max(peak, 1.0)

    def pct(value: float) -> float:
        return round(min(100.0, max(0.0, value / scale * 100.0)), 1)

    return {
        "current_value": current,
        "average_value": average,
        "peak_value": peak,
        "current_percent": pct(current),
        "average_percent": pct(average),
        "peak_percent": pct(peak),
    }
