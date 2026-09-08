from datetime import datetime
import json
import zipfile
from zoneinfo import ZoneInfo

import pytest

from radmon.archive import ArchiveCatalog, QuarterArchiveService, verify_archive
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


class FakeAudit:
    def __init__(self):
        self.actions = []

    def record(self, action, identity, target_type=None, target_id=None, **kwargs):
        self.actions.append(action)


class FakeArchiveStore:
    def __init__(self):
        self.purge_calls = []
        self.rebuild_calls = []
        self.rows = {
            "device": [
                {"serid": 5201, "name": "IS-1", "location": "Gd.52", "maxidlemin": 30,
                 "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "µSv/h", "audiopath": "",
                 "hwaddress": "src", "hwtype": "remote", "description": "prod"},
            ],
            "measurement": [
                {"serid": 5201, "dtom": datetime(2026, 7, 1, 0, 0), "doserate": 1.2,
                 "dose": 0.0042, "previnterval": 2, "stat": 0},
            ],
            "alarm": [
                {"alarmid": 1, "serid": 5201, "dtom": datetime(2026, 7, 2, 0, 0),
                 "type": "ALERT", "msg": "warn"},
            ],
            "rawdata": [],
            "applog": [],
            "news": [],
        }

    def table_rows(self, table, quarter, *, chunk_size=5000):
        yield from self.rows[table]

    def row_counts(self, quarter):
        return {key: len(value) for key, value in self.rows.items()}

    def monthly_recap_rows(self, quarter):
        return [{
            "year": 2026, "month": 7, "serid": 5201, "name": "IS-1", "location": "Gd.52",
            "first_measurement": datetime(2026, 7, 1, 0, 0),
            "last_measurement": datetime(2026, 7, 1, 0, 0),
            "sample_count": 1, "minimum": 1.2, "average": 1.2, "maximum": 1.2,
            "dose_sum": 0.0042, "rate_sum": 1.2, "alert_count": 1, "alarm_count": 0,
        }]

    def purge_quarter(self, quarter):
        self.purge_calls.append(quarter.quarter_id)
        return {"measurement": 1}

    def rebuild_recent(self, quarter):
        self.rebuild_calls.append(quarter.quarter_id)


def make_archive_service(tmp_path, *, verifier=verify_archive):
    security = SecurityStore(tmp_path / "security.db")
    catalog = ArchiveCatalog(security, tmp_path / "archives")
    store = FakeArchiveStore()
    audit = FakeAudit()
    service = QuarterArchiveService(
        store,
        catalog,
        audit,
        tmp_path / "archives",
        verifier=verifier,
    )
    return service, store, catalog, audit


def test_archive_package_contains_required_payloads_and_preserves_stored_dose(tmp_path):
    service, store, catalog, audit = make_archive_service(tmp_path)
    q = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    path = service.export_quarter(q, {"gd52:5201": "2026-09-30T23:59:58+07:00"})
    with zipfile.ZipFile(path) as archive:
        required = {
            "manifest.json", "monthly-recap.csv", "device.csv", "measurement.csv",
            "alarm.csv", "rawdata.csv", "applog.csv", "news.csv", "radmon-2026-Q3.sql",
        }
        assert required <= set(archive.namelist())
        measurement = archive.read("measurement.csv").decode("utf-8")
        sql = archive.read("radmon-2026-Q3.sql").decode("utf-8")
        manifest = json.loads(archive.read("manifest.json"))
    assert "0.0042" in measurement
    assert "0.0042" in sql
    assert manifest["row_counts"]["measurement"] == 1
    verified = verify_archive(path, expected_quarter=q)
    assert verified["quarter_id"] == "2026-Q3"


def test_verify_failure_never_purges(tmp_path):
    def broken_verifier(path, expected_quarter=None):
        raise RuntimeError("checksum mismatch")

    service, store, catalog, audit = make_archive_service(tmp_path, verifier=broken_verifier)
    q = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    q4 = quarter_for(datetime(2026, 10, 2, tzinfo=WIB))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        service.run_rollover(q, drain_info={}, active_quarter=q4)
    assert store.purge_calls == []
    assert catalog.get("2026-Q3")["state"] == "VERIFYING"


def test_verified_archive_purges_once_rebuilds_recent_and_is_idempotent(tmp_path):
    service, store, catalog, audit = make_archive_service(tmp_path)
    q = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    q4 = quarter_for(datetime(2026, 10, 2, tzinfo=WIB))
    first = service.run_rollover(q, drain_info={"gd52:5201": "2026-09-30T23:59:58+07:00"}, active_quarter=q4)
    second = service.run_rollover(q, drain_info={}, active_quarter=q4)
    assert first["state"] == "COMPLETE"
    assert second["state"] == "COMPLETE"
    assert store.purge_calls == ["2026-Q3"]
    assert store.rebuild_calls == ["2026-Q4"]
    assert "ARCHIVE_COMPLETE" in audit.actions


class OldestCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        assert "SELECT MIN(dtom) FROM measurement" in " ".join(sql.split())

    def fetchone(self):
        return (datetime(2026, 7, 1, 0, 0, 0),)


class OldestConnection:
    def cursor(self):
        return OldestCursor()

    def close(self):
        pass


def test_archive_store_can_find_oldest_central_measurement():
    store = CentralArchiveStore(object(), connection_factory=OldestConnection)
    assert store.oldest_measurement_time() == datetime(2026, 7, 1, 0, 0, 0)
