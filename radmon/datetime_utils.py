from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_database_datetime(value: Any) -> datetime | None:
    """Parse the datetime representations returned by MariaDB drivers.

    MariaDB connectors may return a ``datetime`` instance or either an ISO
    string or a traditional ``DATETIME`` string. Invalid and empty values are
    intentionally treated as missing so callers can apply their existing
    source-specific fallback behaviour.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
