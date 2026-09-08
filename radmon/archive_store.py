from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterator

from .quarters import Quarter


TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "device": (
        "serid", "name", "location", "maxidlemin", "warnlevel", "alarmlevel",
        "unit", "audiopath", "hwaddress", "hwtype", "description",
    ),
    "measurement": ("serid", "dtom", "doserate", "dose", "previnterval", "stat"),
    "alarm": ("alarmid", "serid", "dtom", "type", "msg"),
    "rawdata": ("rawid", "serid", "dtom", "raw"),
    "applog": ("logid", "dtom", "msg"),
    "news": ("newsid", "dtom", "title", "content"),
}

TIME_COLUMNS: dict[str, str] = {
    "measurement": "dtom",
    "alarm": "dtom",
    "rawdata": "dtom",
    "applog": "dtom",
    "news": "dtom",
}


class CentralArchiveStore:
    """Read/archive/purge quarter data from central MariaDB only."""

    def __init__(self, settings, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self._connection_factory = connection_factory

    def _connection(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        from .db import connect_mariadb
        return connect_mariadb(self.settings)

    @staticmethod
    def _db_time(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo is not None else value

    @staticmethod
    def _dict_row(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
        return dict(row) if isinstance(row, dict) else dict(zip(columns, row))

    def table_rows(
        self,
        table: str,
        quarter: Quarter,
        *,
        chunk_size: int = 5000,
    ) -> Iterator[dict[str, Any]]:
        if table not in TABLE_COLUMNS:
            raise ValueError(f"archive table tidak dikenal: {table}")
        columns = TABLE_COLUMNS[table]
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                select = ", ".join(columns)
                if table == "device":
                    cursor.execute(f"SELECT {select} FROM device ORDER BY serid")
                else:
                    time_column = TIME_COLUMNS[table]
                    cursor.execute(
                        f"SELECT {select} FROM {table} "
                        f"WHERE {time_column} >= ? AND {time_column} < ? "
                        f"ORDER BY {time_column} ASC",
                        (self._db_time(quarter.start), self._db_time(quarter.end)),
                    )
                while True:
                    rows = cursor.fetchmany(max(1, int(chunk_size)))
                    if not rows:
                        break
                    for row in rows:
                        yield self._dict_row(row, columns)
        finally:
            connection.close()

    def row_counts(self, quarter: Quarter) -> dict[str, int]:
        result: dict[str, int] = {}
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                for table in TABLE_COLUMNS:
                    if table == "device":
                        cursor.execute("SELECT COUNT(*) FROM device")
                    else:
                        time_column = TIME_COLUMNS[table]
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE {time_column} >= ? AND {time_column} < ?",
                            (self._db_time(quarter.start), self._db_time(quarter.end)),
                        )
                    row = cursor.fetchone()
                    value = row.get("COUNT(*)") if isinstance(row, dict) else (row[0] if row else 0)
                    result[table] = int(value or 0)
            return result
        finally:
            connection.close()

    def monthly_recap_rows(self, quarter: Quarter) -> list[dict[str, Any]]:
        devices = {int(row["serid"]): row for row in self.table_rows("device", quarter)}
        months = range((quarter.number - 1) * 3 + 1, (quarter.number - 1) * 3 + 4)
        recap: dict[tuple[int, int], dict[str, Any]] = {}
        for month in months:
            for serid, device in devices.items():
                recap[(month, serid)] = {
                    "year": quarter.year,
                    "month": month,
                    "serid": serid,
                    "name": str(device.get("name") or ""),
                    "location": str(device.get("location") or ""),
                    "first_measurement": None,
                    "last_measurement": None,
                    "sample_count": 0,
                    "minimum": None,
                    "average": None,
                    "maximum": None,
                    "dose_sum": 0.0,
                    "rate_sum": 0.0,
                    "alert_count": 0,
                    "alarm_count": 0,
                }
        for row in self.table_rows("measurement", quarter):
            serid = int(row["serid"])
            measured_at = row.get("dtom")
            if not isinstance(measured_at, datetime):
                continue
            key = (measured_at.month, serid)
            if key not in recap:
                device = devices.get(serid, {})
                recap[key] = {
                    "year": measured_at.year,
                    "month": measured_at.month,
                    "serid": serid,
                    "name": str(device.get("name") or ""),
                    "location": str(device.get("location") or ""),
                    "first_measurement": None,
                    "last_measurement": None,
                    "sample_count": 0,
                    "minimum": None,
                    "average": None,
                    "maximum": None,
                    "dose_sum": 0.0,
                    "rate_sum": 0.0,
                    "alert_count": 0,
                    "alarm_count": 0,
                }
            item = recap[key]
            rate = row.get("doserate")
            if rate is None:
                continue
            rate_value = float(rate)
            item["sample_count"] += 1
            item["rate_sum"] += rate_value
            item["dose_sum"] += float(row.get("dose") or 0.0)
            item["minimum"] = rate_value if item["minimum"] is None else min(float(item["minimum"]), rate_value)
            item["maximum"] = rate_value if item["maximum"] is None else max(float(item["maximum"]), rate_value)
            first = item["first_measurement"]
            last = item["last_measurement"]
            item["first_measurement"] = measured_at if first is None or measured_at < first else first
            item["last_measurement"] = measured_at if last is None or measured_at > last else last
        for row in self.table_rows("alarm", quarter):
            serid = int(row["serid"])
            event_time = row.get("dtom")
            if not isinstance(event_time, datetime):
                continue
            key = (event_time.month, serid)
            if key not in recap:
                continue
            level = str(row.get("type") or "").upper()
            if level == "ALERT":
                recap[key]["alert_count"] += 1
            elif level == "ALARM":
                recap[key]["alarm_count"] += 1
        rows = []
        for key in sorted(recap):
            item = dict(recap[key])
            count = int(item["sample_count"])
            item["average"] = float(item["rate_sum"]) / count if count else None
            rows.append(item)
        return rows

    def purge_quarter(self, quarter: Quarter) -> dict[str, int]:
        connection = self._connection()
        deleted: dict[str, int] = {}
        try:
            with connection.cursor() as cursor:
                for table, time_column in TIME_COLUMNS.items():
                    cursor.execute(
                        f"DELETE FROM {table} WHERE {time_column} >= ? AND {time_column} < ?",
                        (self._db_time(quarter.start), self._db_time(quarter.end)),
                    )
                    deleted[table] = int(getattr(cursor, "rowcount", 0) or 0)
            connection.commit()
            return deleted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rebuild_recent(self, active_quarter: Quarter) -> None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM recent")
                cursor.execute(
                    "SELECT DISTINCT serid FROM measurement WHERE dtom >= ? AND dtom < ? ORDER BY serid",
                    (self._db_time(active_quarter.start), self._db_time(active_quarter.end)),
                )
                serid_rows = cursor.fetchall()
                for raw in serid_rows:
                    serid = int(raw.get("serid") if isinstance(raw, dict) else raw[0])
                    cursor.execute(
                        """
SELECT MIN(dtom), MAX(dtom), MIN(doserate), MAX(doserate), AVG(doserate),
       MIN(dose), MAX(dose), AVG(dose), COUNT(*)
FROM measurement
WHERE serid = ? AND dtom >= ? AND dtom < ?
""",
                        (serid, self._db_time(active_quarter.start), self._db_time(active_quarter.end)),
                    )
                    aggregate = cursor.fetchone()
                    if not aggregate:
                        continue
                    values = list(aggregate.values()) if isinstance(aggregate, dict) else list(aggregate)
                    firstmea, lastmea, minrate, maxrate, avgrate, mindose, maxdose, avgdose, meacount = values[:9]
                    cursor.execute(
                        """
SELECT dtom, doserate, dose, previnterval
FROM measurement WHERE serid = ? AND dtom >= ? AND dtom < ?
ORDER BY dtom DESC LIMIT 2
""",
                        (serid, self._db_time(active_quarter.start), self._db_time(active_quarter.end)),
                    )
                    latest_rows = cursor.fetchall()
                    latest = latest_rows[0]
                    previous = latest_rows[1] if len(latest_rows) > 1 else latest

                    def get(row, key, index):
                        return row.get(key) if isinstance(row, dict) else row[index]

                    latest_time = get(latest, "dtom", 0)
                    latest_rate = get(latest, "doserate", 1)
                    latest_dose = get(latest, "dose", 2)
                    latest_interval = get(latest, "previnterval", 3)
                    previous_rate = get(previous, "doserate", 1)
                    previous_dose = get(previous, "dose", 2)
                    cursor.execute(
                        """
INSERT INTO recent
  (serid, dtom, doserate, dose, lastrate, minrate, maxrate, avgrate,
   lastdose, mindose, maxdose, avgdose, firstmea, lastmea, lastmeasec, meacount)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                        (
                            serid, latest_time, latest_rate, latest_dose, previous_rate,
                            minrate, maxrate, avgrate, previous_dose, mindose, maxdose,
                            avgdose, firstmea, lastmea, int(latest_interval or 0), int(meacount or 0),
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
