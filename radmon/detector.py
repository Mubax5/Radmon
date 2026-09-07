from __future__ import annotations

import math


def parse_detector_line(raw: str) -> float:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty detector line")
    try:
        value = float(text[:7])
    except ValueError as exc:
        raise ValueError(f"invalid detector line: {text!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid dose-rate value: {value!r}")
    return value
