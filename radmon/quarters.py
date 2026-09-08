from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class Quarter:
    year: int
    number: int
    start: datetime
    end: datetime

    @property
    def quarter_id(self) -> str:
        return f"{self.year}-Q{self.number}"

    @property
    def month_names(self) -> tuple[str, str, str]:
        first = (self.number - 1) * 3 + 1
        return tuple(calendar.month_name[month] for month in range(first, first + 3))


def _localize(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _quarter(year: int, number: int, timezone_name: str) -> Quarter:
    zone = ZoneInfo(timezone_name)
    start_month = (number - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=zone)
    if number == 4:
        end = datetime(year + 1, 1, 1, tzinfo=zone)
    else:
        end = datetime(year, start_month + 3, 1, tzinfo=zone)
    return Quarter(year=year, number=number, start=start, end=end)


def quarter_for(value: datetime, timezone_name: str = "Asia/Jakarta") -> Quarter:
    local = _localize(value, timezone_name)
    number = ((local.month - 1) // 3) + 1
    return _quarter(local.year, number, timezone_name)


def previous_quarter(value: datetime, timezone_name: str = "Asia/Jakarta") -> Quarter:
    current = quarter_for(value, timezone_name)
    if current.number == 1:
        return _quarter(current.year - 1, 4, timezone_name)
    return _quarter(current.year, current.number - 1, timezone_name)


def quarters_overlapping(
    start: datetime,
    end: datetime,
    timezone_name: str = "Asia/Jakarta",
) -> list[Quarter]:
    if end <= start:
        raise ValueError("end must be after start")
    start_local = _localize(start, timezone_name)
    end_local = _localize(end, timezone_name)
    result: list[Quarter] = []
    current = quarter_for(start_local, timezone_name)
    while current.start < end_local:
        if current.end > start_local:
            result.append(current)
        current = _quarter(
            current.year + 1 if current.number == 4 else current.year,
            1 if current.number == 4 else current.number + 1,
            timezone_name,
        )
    return result
