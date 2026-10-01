from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def format_dose_value(value: Any) -> str:
    """Render the shortest exact decimal representation without rounding."""
    if value is None or value == "":
        return "—"
    raw = str(value).strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return raw or "—"
    if not number.is_finite():
        return raw
    if number.is_zero():
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
