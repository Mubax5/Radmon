from datetime import datetime

import pytest

from radmon.archive_reports import ArchiveReportRepository


class SealedCatalog:
    def list_archives(self, limit=1000):
        return [{
            "quarter_id": "2026-Q3",
            "start_at": "2026-07-01T00:00:00+07:00",
            "end_at": "2026-10-01T00:00:00+07:00",
            "state": "SEALED",
            "archive_path": "reconciled.zip",
        }]


class SealedRepo(ArchiveReportRepository):
    def _stream_csv(self, item, member):
        assert member == "measurement.csv"
        yield {
            "serid": "5201",
            "dtom": "2026-09-30 23:59:58",
            "doserate": "1.3",
            "dose": "0.0007",
            "previnterval": "2",
            "stat": "0",
        }


def test_reconciled_sealed_archive_is_directly_reportable():
    repo = SealedRepo(SealedCatalog())
    rows = repo.measurement_history(
        datetime(2026, 9, 30, 23, 59, 0),
        datetime(2026, 10, 1, 0, 0, 0),
        serid=5201,
        limit=250,
    )
    assert [row["dose"] for row in rows] == pytest.approx([0.0007])
