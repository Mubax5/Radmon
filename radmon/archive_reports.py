from __future__ import annotations

import csv
from datetime import datetime
import io
from pathlib import Path
from typing import Any, Callable, Iterable
import zipfile
from zoneinfo import ZoneInfo

from .archive import ArchiveCorruptionError, verify_archive
from .quarters import quarter_for


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _as_local_naive(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)


def _summary_from_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    first = None
    last = None
    minimum = None
    maximum = None
    rate_sum = 0.0
    count = 0
    dose_sum = 0.0
    for row in rows:
        measured = row.get("dtom")
        rate = row.get("doserate")
        if not isinstance(measured, datetime) or rate is None:
            continue
        rate_value = float(rate)
        first = measured if first is None or measured < first else first
        last = measured if last is None or measured > last else last
        minimum = rate_value if minimum is None else min(minimum, rate_value)
        maximum = rate_value if maximum is None else max(maximum, rate_value)
        rate_sum += rate_value
        count += 1
        dose_sum += float(row.get("dose") or 0.0)
    return {
        "first_measurement": first,
        "last_measurement": last,
        "minimum": minimum,
        "average": rate_sum / count if count else None,
        "maximum": maximum,
        "sample_count": count,
        "approximate_dose": dose_sum,
        "rate_sum": rate_sum,
    }


def _combine_summaries(parts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    first = None
    last = None
    minimum = None
    maximum = None
    count = 0
    rate_sum = 0.0
    dose_sum = 0.0
    for part in parts:
        part_count = int(part.get("sample_count") or 0)
        if part_count <= 0:
            continue
        part_first = part.get("first_measurement")
        part_last = part.get("last_measurement")
        if isinstance(part_first, str):
            part_first = _parse_datetime(part_first)
        if isinstance(part_last, str):
            part_last = _parse_datetime(part_last)
        if isinstance(part_first, datetime):
            first = part_first if first is None or part_first < first else first
        if isinstance(part_last, datetime):
            last = part_last if last is None or part_last > last else last
        part_min = part.get("minimum")
        part_max = part.get("maximum")
        if part_min is not None:
            minimum = float(part_min) if minimum is None else min(minimum, float(part_min))
        if part_max is not None:
            maximum = float(part_max) if maximum is None else max(maximum, float(part_max))
        part_rate_sum = part.get("rate_sum")
        if part_rate_sum is None:
            average = part.get("average")
            part_rate_sum = float(average) * part_count if average is not None else 0.0
        rate_sum += float(part_rate_sum)
        dose_sum += float(part.get("approximate_dose") or part.get("dose_sum") or 0.0)
        count += part_count
    return {
        "first_measurement": first,
        "last_measurement": last,
        "minimum": minimum,
        "average": rate_sum / count if count else None,
        "maximum": maximum,
        "sample_count": count,
        "approximate_dose": dose_sum,
        "rate_sum": rate_sum,
    }


class ArchiveReportRepository:
    def __init__(self, catalog, *, timezone_name: str = "Asia/Jakarta") -> None:
        self.catalog = catalog
        self.timezone_name = timezone_name

    def _items(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        start_value = _as_local_naive(start, self.timezone_name)
        end_value = _as_local_naive(end, self.timezone_name)
        result = []
        for item in self.catalog.list_archives(limit=1000):
            item_start = _parse_datetime(str(item.get("start_at") or ""))
            item_end = _parse_datetime(str(item.get("end_at") or ""))
            if item_start is None or item_end is None:
                continue
            item_start_n = _as_local_naive(item_start, self.timezone_name)
            item_end_n = _as_local_naive(item_end, self.timezone_name)
            if item_end_n <= start_value or item_start_n >= end_value:
                continue
            if item.get("state") == "DAMAGED":
                raise ArchiveCorruptionError(
                    f"archive {item.get('quarter_id')} rusak: {item.get('last_error') or 'unknown'}"
                )
            if item.get("state") != "COMPLETE":
                continue
            if not item.get("archive_path"):
                raise ArchiveCorruptionError(f"archive {item.get('quarter_id')} tidak memiliki file")
            result.append(item)
        result.sort(key=lambda item: str(item.get("start_at") or ""))
        return result

    def _stream_csv(self, item: dict[str, Any], member: str):
        path = Path(str(item["archive_path"]))
        verify_archive(path)
        with zipfile.ZipFile(path) as archive:
            with archive.open(member) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                    yield from csv.DictReader(text)

    def measurement_history(
        self,
        start: datetime,
        end: datetime,
        *,
        serid: int | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        start_value = _as_local_naive(start, self.timezone_name)
        end_value = _as_local_naive(end, self.timezone_name)
        station_id = int(serid) if serid is not None else None
        rows: list[dict[str, Any]] = []
        for item in self._items(start, end):
            for raw in self._stream_csv(item, "measurement.csv"):
                measured = _parse_datetime(raw.get("dtom"))
                if measured is None:
                    continue
                measured_n = _as_local_naive(measured, self.timezone_name)
                row_serid = int(raw.get("serid") or 0)
                if station_id is not None and row_serid != station_id:
                    continue
                if not (start_value <= measured_n < end_value):
                    continue
                rows.append({
                    "serid": row_serid,
                    "dtom": measured_n,
                    "doserate": float(raw["doserate"]) if raw.get("doserate") not in (None, "") else None,
                    "dose": float(raw["dose"]) if raw.get("dose") not in (None, "") else None,
                    "previnterval": int(raw.get("previnterval") or 0),
                    "stat": int(raw.get("stat") or 0),
                })
                if len(rows) >= max(1, int(limit)):
                    return rows
        rows.sort(key=lambda row: row["dtom"])
        return rows[: max(1, int(limit))]

    def alarm_history(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        serid: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if start is None or end is None:
            complete = [
                item for item in self.catalog.list_archives(limit=1000)
                if item.get("state") == "COMPLETE"
            ]
            if not complete:
                return []
            start_values = [_parse_datetime(str(item.get("start_at") or "")) for item in complete]
            end_values = [_parse_datetime(str(item.get("end_at") or "")) for item in complete]
            start_values = [value for value in start_values if value is not None]
            end_values = [value for value in end_values if value is not None]
            if not start_values or not end_values:
                return []
            start = min(start_values)
            end = max(end_values)
        start_value = _as_local_naive(start, self.timezone_name)
        end_value = _as_local_naive(end, self.timezone_name)
        station_id = int(serid) if serid is not None else None
        rows: list[dict[str, Any]] = []
        for item in self._items(start, end):
            for raw in self._stream_csv(item, "alarm.csv"):
                event_time = _parse_datetime(raw.get("dtom"))
                if event_time is None:
                    continue
                event_n = _as_local_naive(event_time, self.timezone_name)
                row_serid = int(raw.get("serid") or 0)
                if station_id is not None and row_serid != station_id:
                    continue
                if not (start_value <= event_n < end_value):
                    continue
                rows.append({
                    "alarmid": int(raw.get("alarmid") or 0),
                    "serid": row_serid,
                    "dtom": event_n,
                    "type": str(raw.get("type") or ""),
                    "msg": str(raw.get("msg") or ""),
                })
                if len(rows) >= max(1, int(limit)):
                    return rows
        rows.sort(key=lambda row: row["dtom"])
        return rows[: max(1, int(limit))]

    def measurement_summary(self, start: datetime, end: datetime, *, serid: int) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        start_n = _as_local_naive(start, self.timezone_name)
        end_n = _as_local_naive(end, self.timezone_name)
        for item in self._items(start, end):
            raw_start = _parse_datetime(str(item["start_at"]))
            raw_end = _parse_datetime(str(item["end_at"]))
            if raw_start is None or raw_end is None:
                continue
            item_start = _as_local_naive(raw_start, self.timezone_name)
            item_end = _as_local_naive(raw_end, self.timezone_name)
            if start_n <= item_start and end_n >= item_end:
                recap = self.catalog.recap(str(item["quarter_id"]))
                selected = [row for row in recap if int(row.get("serid") or 0) == int(serid)]
                if selected:
                    parts.append(_combine_summaries({
                        "first_measurement": row.get("first_measurement"),
                        "last_measurement": row.get("last_measurement"),
                        "minimum": row.get("minimum"),
                        "average": row.get("average"),
                        "maximum": row.get("maximum"),
                        "sample_count": row.get("sample_count"),
                        "approximate_dose": row.get("dose_sum"),
                        "rate_sum": row.get("rate_sum"),
                    } for row in selected))
                    continue
            partial_start = max(start_n, item_start)
            partial_end = min(end_n, item_end)
            rows = []
            for raw in self._stream_csv(item, "measurement.csv"):
                measured = _parse_datetime(raw.get("dtom"))
                if measured is None or int(raw.get("serid") or 0) != int(serid):
                    continue
                measured_n = _as_local_naive(measured, self.timezone_name)
                if partial_start <= measured_n < partial_end:
                    rows.append({
                        "dtom": measured_n,
                        "doserate": float(raw["doserate"]) if raw.get("doserate") not in (None, "") else None,
                        "dose": float(raw["dose"]) if raw.get("dose") not in (None, "") else None,
                    })
            parts.append(_summary_from_rows(rows))
        return _combine_summaries(parts)

    def station_config(self, serid: int | None = None):
        station_id = int(serid) if serid is not None else None
        items = [item for item in self.catalog.list_archives(limit=1000) if item.get("state") == "COMPLETE"]
        items.sort(key=lambda item: str(item.get("start_at") or ""), reverse=True)
        for item in items:
            for row in self._stream_csv(item, "device.csv"):
                row_serid = int(row.get("serid") or 0)
                if station_id is not None and row_serid != station_id:
                    continue
                from .models import StationConfig
                location = str(row.get("location") or "")
                building = "".join(ch for ch in location if ch.isdigit()) or location
                return StationConfig(
                    row_serid,
                    building,
                    str(row.get("name") or f"Station {row_serid}"),
                    location,
                    float(row.get("warnlevel") or 0),
                    float(row.get("alarmlevel") or 0),
                    int(row.get("maxidlemin") or 30),
                    str(row.get("unit") or "µSv/h"),
                )
        raise KeyError(f"station archive tidak ditemukan: {station_id}")


class CompositeReportRepository:
    def __init__(
        self,
        active_repository,
        archive_repository: ArchiveReportRepository,
        *,
        timezone_name: str = "Asia/Jakarta",
        now: Callable[[], datetime] | None = None,
        active_summary_reader: Any | None = None,
    ) -> None:
        self.active = active_repository
        self.archive = archive_repository
        self.timezone_name = timezone_name
        self.now = now or (lambda: datetime.now(ZoneInfo(timezone_name)))
        self.active_summary_reader = active_summary_reader

    def _active_start(self, like: datetime) -> datetime:
        boundary = quarter_for(self.now(), self.timezone_name).start
        if like.tzinfo is None:
            return boundary.replace(tzinfo=None)
        return boundary.astimezone(like.tzinfo)

    def station_config(self, serid: int | None = None):
        try:
            return self.active.station_config(serid)
        except Exception:
            return self.archive.station_config(serid)

    def measurement_history(self, start: datetime, end: datetime, *, serid: int | None = None, limit: int = 5000):
        boundary = self._active_start(start)
        rows: list[dict[str, Any]] = []
        if start < boundary:
            archived_end = min(end, boundary)
            if archived_end > start:
                rows.extend(self.archive.measurement_history(start, archived_end, serid=serid, limit=limit))
        if end >= boundary and len(rows) < limit:
            rows.extend(self.active.measurement_history(max(start, boundary), end, serid=serid, limit=limit))
        dedup = {}
        for row in rows:
            dedup[(int(row.get("serid") or 0), row.get("dtom"))] = row
        result = sorted(dedup.values(), key=lambda row: row.get("dtom"))
        return result[: max(1, int(limit))]

    def alarm_history(self, start=None, end=None, *, serid: int | None = None, limit: int = 1000):
        if start is None or end is None:
            return self.active.alarm_history(start, end, serid=serid, limit=limit)
        boundary = self._active_start(start)
        rows = []
        if start < boundary:
            archived_end = min(end, boundary)
            if archived_end > start:
                rows.extend(self.archive.alarm_history(start, archived_end, serid=serid, limit=limit))
        if end >= boundary and len(rows) < limit:
            rows.extend(self.active.alarm_history(max(start, boundary), end, serid=serid, limit=limit))
        dedup = {}
        for row in rows:
            dedup[(int(row.get("serid") or 0), row.get("dtom"), row.get("type"), row.get("msg"))] = row
        return sorted(dedup.values(), key=lambda row: row.get("dtom"))[: max(1, int(limit))]

    def _active_summary(self, start: datetime, end: datetime, serid: int) -> dict[str, Any]:
        aggregate = getattr(self.active, "measurement_summary", None)
        if callable(aggregate):
            return aggregate(start, end, serid=serid)
        if self.active_summary_reader is not None:
            return self.active_summary_reader.summary(start, end, serid=serid)
        rows = self.active.measurement_history(start, end, serid=serid, limit=200000)
        return _summary_from_rows(rows)

    def measurement_summary(self, start: datetime, end: datetime, *, serid: int) -> dict[str, Any]:
        boundary = self._active_start(start)
        parts = []
        if start < boundary:
            archived_end = min(end, boundary)
            if archived_end > start:
                parts.append(self.archive.measurement_summary(start, archived_end, serid=serid))
        if end >= boundary:
            active_start = max(start, boundary)
            if end >= active_start:
                parts.append(self._active_summary(active_start, end, serid))
        return _combine_summaries(parts)
