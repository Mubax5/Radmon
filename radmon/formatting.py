from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


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
