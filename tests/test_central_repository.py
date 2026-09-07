from __future__ import annotations

from datetime import datetime

from radmon.central_api import CentralMariaDBRepository
from radmon.config import Settings


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0
    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.connection.executed.append((normalized, tuple(params)))
        self.connection.last_sql = normalized
        self.rowcount = 1 if "INSERT IGNORE INTO measurement" in normalized else 0
    def fetchone(self):
        if "SELECT dtom, doserate, dose FROM measurement" in self.connection.last_sql:
            return (datetime(2026, 9, 7, 9, 59, 58), 0.10, 0.00005)
        if "SELECT dtom FROM recent" in self.connection.last_sql:
            return (datetime(2026, 9, 7, 9, 59, 58),)
        return None
    def fetchall(self): return []
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False


class Connection:
    def __init__(self):
        self.executed = []
        self.last_sql = ""
        self.commits = 0
        self.rollbacks = 0
    def cursor(self): return Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


def test_central_ingest_updates_measurement_and_recent_using_same_schema():
    connection = Connection()
    repository = CentralMariaDBRepository(Settings())
    repository._connect = lambda: connection
    station = {"serid": 5202, "name": "IS-1 Koridor", "location": "Gd.52", "maxidlemin": 30, "warnlevel": 8.0, "alarmlevel": 10.0, "unit": "uSv/h"}
    measurements = [{"serid": 5202, "dtom": datetime(2026, 9, 7, 10, 0, 0), "doserate": 0.12, "dose": 0.000061, "previnterval": 2, "stat": 0}]

    assert repository.ingest_batch(measurements, station, "Gd52-IS1Koridor") == 1

    sql = "\n".join(statement for statement, _ in connection.executed)
    assert "INSERT IGNORE INTO measurement" in sql
    assert "INSERT INTO recent" in sql
    assert "radmon_" not in sql
    assert connection.commits == 1
