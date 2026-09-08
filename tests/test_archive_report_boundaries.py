from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from radmon.archive_reports import CompositeReportRepository

WIB = ZoneInfo("Asia/Jakarta")


class ArchiveRepo:
    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return [
            {"serid": 5201, "dtom": datetime(2026, 9, 30, 23, 59, 58), "doserate": 1.3, "dose": 0.0007, "previnterval": 2, "stat": 0},
        ]

    def measurement_summary(self, start, end, *, serid):
        return {
            "first_measurement": datetime(2026, 9, 30, 23, 59, 58),
            "last_measurement": datetime(2026, 9, 30, 23, 59, 58),
            "minimum": 1.3,
            "average": 1.3,
            "maximum": 1.3,
            "sample_count": 1,
            "approximate_dose": 0.0007,
        }


class ActiveRepo:
    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return [
            {"serid": 5201, "dtom": datetime(2026, 10, 1, 0, 0, 0), "doserate": 1.4, "dose": 0.001, "previnterval": 2, "stat": 0},
        ]

    def measurement_summary(self, start, end, *, serid=None):
        return {
            "first_measurement": datetime(2026, 10, 1, 0, 0, 0),
            "last_measurement": datetime(2026, 10, 1, 0, 0, 0),
            "minimum": 1.4,
            "average": 1.4,
            "maximum": 1.4,
            "sample_count": 1,
            "approximate_dose": 0.001,
        }


def test_exact_archived_quarter_end_does_not_pull_active_boundary_sample():
    repo = CompositeReportRepository(
        ActiveRepo(),
        ArchiveRepo(),
        now=lambda: datetime(2026, 10, 2, 12, 0, tzinfo=WIB),
    )
    rows = repo.measurement_history(
        datetime(2026, 9, 30, 23, 59, 0),
        datetime(2026, 10, 1, 0, 0, 0),
        serid=5201,
        limit=250,
    )
    assert [row["doserate"] for row in rows] == pytest.approx([1.3])
