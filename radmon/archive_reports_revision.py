"""Read production alarm.csv fields while preserving report semantics."""
from __future__ import annotations

from datetime import datetime


def apply() -> None:
    from . import archive_reports as module

    def alarm_history(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        serid: int | None = None,
        limit: int = 1000,
    ):
        if start is None or end is None:
            items = self.catalog.list_archives(limit=1000)
            complete = [item for item in items if item.get("state") in {"COMPLETE", "SEALED", "PURGING"}]
            if not complete:
                return []
            start = min(module._parse_datetime(str(item["start_at"])) for item in complete)
            end = max(module._parse_datetime(str(item["end_at"])) for item in complete)
            if start is None or end is None:
                return []
        start_value = module._as_local_naive(start, self.timezone_name)
        end_value = module._as_local_naive(end, self.timezone_name)
        station_id = int(serid) if serid is not None else None
        rows = []
        for item in self._items(start, end):
            for raw in self._stream_csv(item, "alarm.csv"):
                event_time = module._parse_datetime(raw.get("dtoa") or raw.get("dtom"))
                if event_time is None:
                    continue
                event_n = module._as_local_naive(event_time, self.timezone_name)
                row_serid = int(raw.get("serid") or 0)
                if station_id is not None and row_serid != station_id:
                    continue
                if not (start_value <= event_n < end_value):
                    continue
                level = int(raw.get("lvl") or 0)
                alarm_type = str(raw.get("type") or ("ALARM" if level >= 2 else "ALERT"))
                measured = raw.get("mvalue")
                threshold = raw.get("thvalue")
                message = str(raw.get("msg") or "")
                if not message:
                    message = f"dose={measured or '-'} threshold={threshold or '-'} hit={raw.get('nhit') or 0}"
                rows.append({
                    "alarmid": int(raw.get("alarmid") or 0),
                    "serid": row_serid,
                    "dtom": event_n,
                    "dtoa": event_n,
                    "type": alarm_type,
                    "lvl": level,
                    "msg": message,
                    "mvalue": float(measured) if measured not in (None, "") else None,
                    "thvalue": float(threshold) if threshold not in (None, "") else None,
                    "nhit": int(raw.get("nhit") or 0),
                    "ack": int(raw.get("ack") or 0),
                    "pic": raw.get("pic"),
                    "note": raw.get("note"),
                    "i_op": module._parse_datetime(raw.get("i_op")),
                    "i_flag": int(raw.get("i_flag") or 0),
                })
                if len(rows) >= max(1, int(limit)):
                    return rows
        rows.sort(key=lambda row: row["dtom"])
        return rows[: max(1, int(limit))]

    module.ArchiveReportRepository.alarm_history = alarm_history
