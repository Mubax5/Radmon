from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from radmon.archive import ArchiveCatalog, QuarterArchiveService
from radmon.archive_reports import ArchiveReportRepository, CompositeReportRepository
from radmon.quarters import quarter_for
from radmon.security import SecurityStore

WIB = ZoneInfo("Asia/Jakarta")


class TinyArchiveStore:
    def __init__(self):
        self.rows = {
            "device": [{
                "serid": 5201, "name": "IS-1", "location": "Gd.52", "maxidlemin": 30,
                "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "µSv/h", "audiopath": "",
                "hwaddress": "gd52", "hwtype": "remote", "description": "prod",
            }],
            "measurement": [
                {"serid": 5201, "dtom": datetime(2026, 9, 30, 23, 59, 56), "doserate": 1.2, "dose": 0.0042, "previnterval": 2, "stat": 0},
                {"serid": 5201, "dtom": datetime(2026, 9, 30, 23, 59, 58), "doserate": 1.3, "dose": 0.0007, "previnterval": 2, "stat": 0},
            ],
            "alarm": [{"alarmid": 1, "serid": 5201, "dtom": datetime(2026, 9, 30, 22, 0), "type": "ALERT", "msg": "warn"}],
            "rawdata": [], "applog": [], "news": [],
        }

    def table_rows(self, table, quarter, *, chunk_size=5000):
        yield from self.rows[table]

    def row_counts(self, quarter):
        return {key: len(rows) for key, rows in self.rows.items()}

    def monthly_recap_rows(self, quarter):
        return [{
            "year": 2026, "month": 9, "serid": 5201, "name": "IS-1", "location": "Gd.52",
            "first_measurement": datetime(2026, 9, 30, 23, 59, 56),
            "last_measurement": datetime(2026, 9, 30, 23, 59, 58),
            "sample_count": 2, "minimum": 1.2, "average": 1.25, "maximum": 1.3,
            "dose_sum": 0.0049, "rate_sum": 2.5, "alert_count": 1, "alarm_count": 0,
        }]


def build_archive(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    catalog = ArchiveCatalog(security, tmp_path / "archives")
    service = QuarterArchiveService(TinyArchiveStore(), catalog, None, tmp_path / "archives")
    q3 = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    path = service.export_quarter(q3, {"gd52:5201": "2026-09-30T23:59:58"})
    verified = service.verifier(path, q3)
    security.upsert_archive(
        quarter_id=q3.quarter_id,
        start_at=q3.start.isoformat(), end_at=q3.end.isoformat(), state="COMPLETE",
        archive_path=str(path), archive_sha256=verified["archive_sha256"],
        row_counts=verified["row_counts"], drain=verified["drain"],
        created_at=verified["created_at"], sealed_at=verified["created_at"],
        completed_at=verified["created_at"],
    )
    return catalog


def test_archive_repository_reads_measurements_directly_from_zip(tmp_path):
    catalog = build_archive(tmp_path)
    repo = ArchiveReportRepository(catalog)
    start = datetime(2026, 9, 30, 23, 59, 0)
    end = datetime(2026, 10, 1, 0, 0, 0)
    rows = repo.measurement_history(start, end, serid=5201, limit=250)
    assert [row["dose"] for row in rows] == pytest.approx([0.0042, 0.0007])
    summary = repo.measurement_summary(start, end, serid=5201)
    assert summary["sample_count"] == 2
    assert summary["average"] == pytest.approx(1.25)
    assert summary["approximate_dose"] == pytest.approx(0.0049)


class ActiveRepo:
    def measurement_history(self, start, end, *, serid=None, limit=5000):
        rows = [
            {"serid": 5201, "dtom": datetime(2026, 10, 1, 0, 0, 0), "doserate": 1.4, "dose": 0.001, "previnterval": 2, "stat": 0},
            {"serid": 5201, "dtom": datetime(2026, 10, 1, 0, 0, 2), "doserate": 1.5, "dose": 0.002, "previnterval": 2, "stat": 0},
        ]
        return [row for row in rows if start <= row["dtom"] <= end][:limit]

    def measurement_summary(self, start, end, *, serid=None):
        rows = self.measurement_history(start, end, serid=serid, limit=1000)
        rates = [row["doserate"] for row in rows]
        return {
            "first_measurement": rows[0]["dtom"] if rows else None,
            "last_measurement": rows[-1]["dtom"] if rows else None,
            "minimum": min(rates) if rates else None,
            "average": sum(rates) / len(rates) if rates else None,
            "maximum": max(rates) if rates else None,
            "sample_count": len(rates),
            "approximate_dose": sum(row["dose"] for row in rows),
        }

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return []


def test_composite_repository_merges_archive_and_active_quarters(tmp_path):
    archive_repo = ArchiveReportRepository(build_archive(tmp_path))
    repo = CompositeReportRepository(
        ActiveRepo(), archive_repo,
        now=lambda: datetime(2026, 10, 2, 12, 0, tzinfo=WIB),
    )
    rows = repo.measurement_history(
        datetime(2026, 9, 30, 23, 59, 0),
        datetime(2026, 10, 1, 0, 0, 3),
        serid=5201,
        limit=250,
    )
    assert [row["doserate"] for row in rows] == pytest.approx([1.2, 1.3, 1.4, 1.5])
    summary = repo.measurement_summary(
        datetime(2026, 9, 30, 23, 59, 0),
        datetime(2026, 10, 1, 0, 0, 3),
        serid=5201,
    )
    assert summary["sample_count"] == 4
    assert summary["average"] == pytest.approx(1.35)
    assert summary["approximate_dose"] == pytest.approx(0.0079)
