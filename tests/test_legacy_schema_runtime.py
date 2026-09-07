from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from radmon.config import Settings
from radmon.models import Measurement
from radmon.repository import MariaDBRepository


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = 77
        self.rowcount = 1

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.connection.executed.append((normalized, tuple(params)))
        self.connection.last_sql = normalized
        return self

    def fetchone(self):
        if "SELECT dtom, doserate, dose FROM measurement" in self.connection.last_sql:
            return self.connection.previous_measurement
        if "FROM device" in self.connection.last_sql:
            return self.connection.device_row
        if "FROM recent" in self.connection.last_sql:
            return self.connection.recent_row
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.last_sql = ""
        self.previous_measurement = (datetime(2026, 9, 7, 10, 0, 0), 0.12, 0.00006)
        self.device_row = (5201, "R. Lab Iradiasi", "Gedung 52", 30, 8, 10, "uSv/h")
        self.recent_row = None
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_measurement_write_uses_only_user_schema_and_updates_recent():
    connection = FakeConnection()
    repo = MariaDBRepository(Settings(), connection_factory=lambda: connection)
    sample = Measurement(5201, datetime(2026, 9, 7, 10, 0, 2), 0.18, 2, 0)

    repo.insert_measurement(sample, raw="000.180")

    sql = "\n".join(statement for statement, _ in connection.executed)
    assert "INSERT INTO rawdata" in sql
    assert "INSERT INTO measurement" in sql
    assert "INSERT INTO recent" in sql
    assert "radmon_sync_queue" not in sql
    assert "radmon_alarm_event" not in sql

    measurement_sql, measurement_params = next(
        item for item in connection.executed if "INSERT INTO measurement" in item[0]
    )
    assert "dose" in measurement_sql
    assert measurement_params[:3] == (5201, datetime(2026, 9, 7, 10, 0, 2), 0.18)
    assert measurement_params[3] == pytest.approx((0.12 + 0.18) / 2 * 2 / 3600)
    assert connection.commits == 1


def test_alarm_history_and_writes_use_existing_alarm_table_only():
    connection = FakeConnection()
    repo = MariaDBRepository(Settings(), connection_factory=lambda: connection)

    repo.alarm_history(serid=5201, limit=50)
    repo.record_alarm(5201, "ALERT", "Dose rate 8.5 uSv/h", at=datetime(2026, 9, 7, 10, 0, 0))

    sql = "\n".join(statement for statement, _ in connection.executed)
    assert "FROM alarm" in sql
    assert "INSERT INTO alarm" in sql
    assert "radmon_alarm_event" not in sql
    assert "acknowledged_at" not in sql
    assert "last_value" not in sql


def test_no_extension_schema_is_required_by_the_application():
    assert not Path("database/schema_extension.sql").exists()
    source = Path("radmon/repository.py").read_text(encoding="utf-8")
    central = Path("radmon/central_api.py").read_text(encoding="utf-8")
    for forbidden in ("radmon_alarm_event", "radmon_sync_queue", "radmon_sync_receipt"):
        assert forbidden not in source
        assert forbidden not in central
