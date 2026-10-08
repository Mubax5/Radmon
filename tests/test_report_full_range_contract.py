from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from radmon.config import Settings
from radmon.models import StationConfig
from radmon.reports import ReportService


class LargeReportRepository:
    def __init__(self, count: int = 1_201) -> None:
        self.count = count
        self.measurement_limits: list[int] = []

    def station_config(self, serid=None):
        return StationConfig(5201, "52", "IS-1", "Gd.52", 8, 10, 30, "uSv/h")

    def measurement_count(self, start, end, *, serid=None):
        return self.count

    def measurement_history(self, start, end, *, serid=None, limit=5000):
        self.measurement_limits.append(limit)
        return [
            {
                "serid": serid,
                "dtom": start + timedelta(seconds=index),
                "doserate": 0.1 + index / 10_000,
                "dose": 0.0,
                "previnterval": 2,
                "stat": 0,
            }
            for index in range(min(self.count, limit))
        ]

    def measurement_summary(self, start, end, *, serid=None):
        return {
            "first_measurement": start,
            "last_measurement": start + timedelta(seconds=self.count - 1),
            "minimum": 0.1,
            "average": 0.1600,
            "maximum": 0.2200,
            "sample_count": self.count,
            "approximate_dose": 0.0,
        }

    def alarm_count(self, start, end, *, serid=None):
        return 0

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return []


def test_full_pdf_fetches_all_rows_and_preview_is_explicitly_partial():
    repository = LargeReportRepository()
    start = datetime(2026, 9, 7, 8, 0)
    service = ReportService(repository, Settings().for_dummy())

    preview = service.pdf_bytes(start, start + timedelta(hours=1), preview=True)
    assert b"Pratinjau: menampilkan 250 dari 1,201 pengukuran" in preview
    assert repository.measurement_limits[-1] == ReportService.PREVIEW_ROW_LIMIT

    full = service.pdf_bytes(start, start + timedelta(hours=1))
    assert b"Sample count: 1,201" in full
    assert b"2026-09-07 08:00:00 WIB" in full
    assert b"2026-09-07 08:20:00 WIB" in full
    assert repository.measurement_limits[-1] == ReportService.MAX_MEASUREMENT_ROWS + 1


def test_full_report_rejects_a_silently_truncated_history_result():
    class TruncatedRepository(LargeReportRepository):
        def measurement_history(self, start, end, *, serid=None, limit=5000):
            self.measurement_limits.append(limit)
            return super().measurement_history(start, end, serid=serid, limit=min(limit, 1_000))

    service = ReportService(TruncatedRepository(), Settings().for_dummy())
    start = datetime(2026, 9, 7, 8, 0)
    with pytest.raises(ValueError, match="data report tidak lengkap"):
        service.pdf_bytes(start, start + timedelta(hours=1))


@pytest.mark.parametrize("tz", [timezone.utc, ZoneInfo("Asia/Jakarta")])
def test_report_range_accepts_exactly_24_hours_in_utc_and_wib(tz):
    start = datetime(2026, 10, 1, 0, 0, tzinfo=tz)
    assert ReportService.validate_range(start, start + timedelta(hours=24)) == timedelta(hours=24)
    with pytest.raises(ValueError, match="24 jam"):
        ReportService.validate_range(start, start + timedelta(hours=24, seconds=1))


def test_report_range_uses_elapsed_time_across_dst_not_wall_clock_time():
    start = datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    # The same local wall-clock addition spans 25 elapsed hours at the DST fall-back.
    with pytest.raises(ValueError, match="24 jam"):
        ReportService.validate_range(start, start + timedelta(days=1))


def test_reports_page_explains_wib_and_preview_limit():
    root = Path(__file__).resolve().parents[1]
    page = (root / "web/src/pages/ReportsPage.tsx").read_text(encoding="utf-8")
    assert "MAX_REPORT_RANGE_MS = 24 * 60 * 60 * 1000" in page
    assert "tepat 24 jam diperbolehkan" in page
    assert "Pratinjau: maksimal 250 baris" in page
    assert "PDF penuh yang dibuat dan diunduh memuat seluruh data" in page
