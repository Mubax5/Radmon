from datetime import datetime
import zipfile
from zoneinfo import ZoneInfo

import pytest

from radmon.archive import ArchiveCatalog, ArchiveCorruptionError, QuarterArchiveService, verify_archive
from radmon.quarters import quarter_for
from radmon.security import SecurityStore

WIB = ZoneInfo("Asia/Jakarta")


class TinyStore:
    def __init__(self):
        self.rows = {
            "device": [{
                "serid": 5201, "name": "IS-1", "location": "Gd.52", "maxidlemin": 30,
                "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "µSv/h", "audiopath": "",
                "hwaddress": "gd52", "hwtype": "remote", "description": "prod",
            }],
            "measurement": [{
                "serid": 5201, "dtom": datetime(2026, 7, 1), "doserate": 1.2,
                "dose": 0.0042, "previnterval": 2, "stat": 0,
            }],
            "alarm": [], "rawdata": [], "applog": [], "news": [],
        }

    def table_rows(self, table, quarter, *, chunk_size=5000):
        yield from self.rows[table]

    def row_counts(self, quarter):
        return {key: len(rows) for key, rows in self.rows.items()}

    def monthly_recap_rows(self, quarter):
        return []


def make_archive(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    catalog = ArchiveCatalog(security, tmp_path / "archives")
    service = QuarterArchiveService(TinyStore(), catalog, None, tmp_path / "archives")
    quarter = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    path = service.export_quarter(quarter, {})
    return path, quarter


def test_verify_archive_surfaces_tampered_payload(tmp_path):
    path, quarter = make_archive(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "measurement.csv",
            "serid,dtom,doserate,dose,previnterval,stat\n"
            "5201,2026-07-01 00:00:00,9.9,0.0042,2,0\n",
        )
    with pytest.raises(ArchiveCorruptionError, match="checksum mismatch"):
        verify_archive(path, quarter)


def test_reconcile_marks_indexed_missing_archive_damaged(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    catalog = ArchiveCatalog(security, tmp_path / "archives")
    quarter = quarter_for(datetime(2026, 9, 8, tzinfo=WIB))
    missing = tmp_path / "archives" / "2026" / "missing.zip"
    security.upsert_archive(
        quarter_id=quarter.quarter_id,
        start_at=quarter.start.isoformat(),
        end_at=quarter.end.isoformat(),
        state="COMPLETE",
        archive_path=str(missing),
    )
    catalog.reconcile()
    row = security.get_archive(quarter.quarter_id)
    assert row["state"] == "DAMAGED"
    assert "missing" in row["last_error"]
