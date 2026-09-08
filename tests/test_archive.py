from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from radmon.archive_store import CentralArchiveStore
from radmon.quarters import quarter_for
from radmon.security import SecurityStore

WIB = ZoneInfo("Asia/Jakarta")


def test_archive_state_survives_store_reopen(tmp_path):
    path = tmp_path / "security.db"
    store = SecurityStore(path)
    store.upsert_archive(
        quarter_id="2026-Q3",
        start_at="2026-07-01T00:00:00+07:00",
        end_at="2026-10-01T00:00:00+07:00",
        state="OPEN",
    )
    store.update_archive_state("2026-Q3", "EXPORTING", last_error=None)
    reopened = SecurityStore(path)
    row = reopened.get_archive("2026-Q3")
    assert row["state"] == "EXPORTING"
    assert row["quarter_id"] == "2026-Q3"


class RecordingCursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 2

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return None


class RecordingConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_purge_only_deletes_old_quarter_operational_rows():
    connection = RecordingConnection()
    q = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    store = CentralArchiveStore(object(), connection_factory=lambda: connection)
    store.purge_quarter(q)
    sql = "\n".join(call[0] for call in connection.cursor_obj.calls)
    assert "DELETE FROM measurement" in sql
    assert "DELETE FROM alarm" in sql
    assert "DELETE FROM rawdata" in sql
    assert "DELETE FROM applog" in sql
    assert "DELETE FROM news" in sql
    assert "DELETE FROM device" not in sql
    assert connection.committed is True


def test_monthly_recap_sums_stored_measurement_dose_without_reintegration():
    q = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))

    class FakeStore(CentralArchiveStore):
        def __init__(self):
            pass

        def table_rows(self, table, quarter, *, chunk_size=5000):
            if table == "device":
                yield {"serid": 5201, "name": "IS-1", "location": "Gd.52"}
            elif table == "measurement":
                yield {"serid": 5201, "dtom": datetime(2026, 7, 1, 0, 0), "doserate": 1.2, "dose": 0.0042, "previnterval": 2, "stat": 0}
                yield {"serid": 5201, "dtom": datetime(2026, 7, 1, 0, 0, 2), "doserate": 1.3, "dose": 0.0007, "previnterval": 2, "stat": 0}
            elif table == "alarm":
                yield {"serid": 5201, "dtom": datetime(2026, 7, 2, 0, 0), "type": "ALERT", "msg": "warn"}
                yield {"serid": 5201, "dtom": datetime(2026, 7, 3, 0, 0), "type": "ALARM", "msg": "alarm"}
            else:
                return

    rows = FakeStore().monthly_recap_rows(q)
    july = next(row for row in rows if row["month"] == 7 and row["serid"] == 5201)
    assert july["sample_count"] == 2
    assert july["dose_sum"] == pytest.approx(0.0049)
    assert july["minimum"] == pytest.approx(1.2)
    assert july["average"] == pytest.approx(1.25)
    assert july["maximum"] == pytest.approx(1.3)
    assert july["alert_count"] == 1
    assert july["alarm_count"] == 1
