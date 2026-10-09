from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def normalize_dose_unit(value: Any) -> str:
    """Return a display-stable dose-rate unit while preserving custom units."""
    text = str(value or "µSv/h").strip().replace("μ", "µ")
    if text.lower() == "usv/h":
        return "µSv/h"
    return text


def format_dose_value(value: Any) -> str:
    """Render a dose value rounded to exactly two fractional digits."""
    if value is None or value == "":
        return "—"
    raw = str(value).strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return raw or "—"
    if not number.is_finite():
        return raw
    try:
        return format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    except InvalidOperation:
        return raw
