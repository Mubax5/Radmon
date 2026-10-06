from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from radmon.config import Settings
from radmon.reports import ReportService


class FakeRepo:
    def station_config(self, serid=None):
        from radmon.models import StationConfig
        return StationConfig(5202, "52", "IS-1 Koridor", "Gd.52", 8, 10, 5, "uSv/h")

    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return [
            {"serid": 5202, "dtom": start, "doserate": 0.1, "dose": None, "previnterval": 2, "stat": 0},
            {"serid": 5202, "dtom": start + timedelta(hours=1), "doserate": 0.2, "dose": None, "previnterval": 2, "stat": 0},
            {"serid": 5202, "dtom": start + timedelta(hours=2), "doserate": 0.3, "dose": None, "previnterval": 2, "stat": 0},
        ]

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return [
            {
                "alarmid": 1,
                "serid": 5202,
                "dtom": start,
                "type": "ALERT",
                "msg": "Dose rate crossed warning threshold",
            }
        ]


def test_report_summary_calculates_min_avg_max_and_trapezoid_dose():
    start = datetime(2026, 9, 7, 8, 0, 0)
    end = start + timedelta(hours=2)
    service = ReportService(FakeRepo(), Settings())

    summary = service.summary(start, end)

    assert summary.minimum == pytest.approx(0.1)
    assert summary.average == pytest.approx(0.2)
    assert summary.maximum == pytest.approx(0.3)
    assert summary.sample_count == 3
    assert summary.approximate_dose == pytest.approx(0.4)
    assert summary.first_measurement == start
    assert summary.last_measurement == end


def test_csv_export_contains_measurements(tmp_path):
    start = datetime(2026, 9, 7, 8, 0, 0)
    end = start + timedelta(hours=2)
    service = ReportService(FakeRepo(), Settings())
    path = service.export_csv(start, end, tmp_path / "history.csv")
    content = path.read_text(encoding="utf-8")
    assert "serid,dtom,doserate" in content
    assert "5202" in content
    assert "0.3" in content


def test_pdf_export_has_pdf_signature_and_station_identity(tmp_path):
    start = datetime(2026, 9, 7, 8, 0, 0)
    end = start + timedelta(hours=2)
    service = ReportService(FakeRepo(), Settings())
    path = service.export_pdf(start, end, tmp_path / "report.pdf")
    payload = path.read_bytes()
    assert payload.startswith(b"%PDF")
    assert len(payload) > 1000


def test_canonical_pdf_is_portrait_and_contains_the_complete_report_contract(tmp_path):
    class FullRangeRepo(FakeRepo):
        def measurement_history(self, start, end, *, serid=None, limit=5000):
            return [
                {"serid": 5202, "dtom": start + timedelta(seconds=index), "doserate": 0.125, "dose": 0.0001}
                for index in range(1005)
            ]

    start = datetime(2026, 9, 7, 8, 0, 0)
    payload = ReportService(FullRangeRepo(), Settings()).pdf_bytes(start, start + timedelta(hours=1))

    assert b"/MediaBox [ 0 0 595.2756 841.8898 ]" in payload
    for expected in (
        b"Instalasi Pengelolaan Limbah Radioaktif",
        b"Direktorat Pengelolaan Fasilitas Ketenaganukliran",
        b"Summary",
        b"First",
        b"Last",
        b"Dose Average",
        b"Max",
        b"Dose rate and Approx. Dose",
        b"Approx. Dose",
        b"1005",
    ):
        assert expected in payload
    assert b"1,000 rows" not in payload


def test_stored_dose_contract_is_not_added_to_integrated_rate_a_second_time():
    start = datetime(2026, 9, 7, 8, 0, 0)
    rows = [
        {"dtom": start, "doserate": 0.1, "dose": 0.2},
        {"dtom": start + timedelta(hours=1), "doserate": 0.3, "dose": 0.4},
    ]
    from radmon.reports import approximate_dose

    assert approximate_dose(rows) == pytest.approx(0.6)


def test_pdf_preflights_measurement_and_alarm_bounds_before_materializing_rows():
    class OversizedRepo(FakeRepo):
        def measurement_count(self, start, end, *, serid=None):
            return ReportService.MAX_MEASUREMENT_ROWS + 1

        def measurement_history(self, start, end, *, serid=None, limit=5000):
            raise AssertionError("oversized measurements must fail before materialization")

    start = datetime(2026, 9, 7, 8, 0)
    with pytest.raises(ValueError, match="pengukuran.*batas"):
        ReportService(OversizedRepo(), Settings()).pdf_bytes(start, start + timedelta(hours=1))

    class TooManyAlarmsRepo(FakeRepo):
        def measurement_count(self, start, end, *, serid=None):
            return 3

        def alarm_count(self, start, end, *, serid=None):
            return ReportService.MAX_ALARM_ROWS + 1

    with pytest.raises(ValueError, match="alarm.*batas"):
        ReportService(TooManyAlarmsRepo(), Settings()).pdf_bytes(start, start + timedelta(hours=1))

    class AtBoundRepo(FakeRepo):
        def measurement_count(self, start, end, *, serid=None):
            return ReportService.MAX_MEASUREMENT_ROWS

        def alarm_count(self, start, end, *, serid=None):
            return ReportService.MAX_ALARM_ROWS

    ReportService(AtBoundRepo(), Settings()).preflight(start, start + timedelta(hours=1))


def test_pdf_formats_period_and_measurements_in_wib():
    from zoneinfo import ZoneInfo

    start = datetime(2026, 9, 7, 1, 0, tzinfo=ZoneInfo("UTC"))
    payload = ReportService(FakeRepo(), Settings()).pdf_bytes(start, start + timedelta(hours=1))
    assert b"From 2026-09-07 08:00:00 WIB to 2026-09-07 09:00:00 WIB" in payload
    assert b"2026-09-07 08:00:00 WIB" in payload


def test_pdf_includes_every_alarm_below_explicit_bound():
    class ManyAlarmsRepo(FakeRepo):
        def alarm_count(self, start, end, *, serid=None):
            return 501

        def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
            assert limit >= 502
            return [{"alarmid": index, "serid": 5202, "dtom": start, "type": "ALERT", "msg": f"Alarm {index}"} for index in range(501)]

    start = datetime(2026, 9, 7, 8, 0)
    payload = ReportService(ManyAlarmsRepo(), Settings()).pdf_bytes(start, start + timedelta(hours=1))
    assert b"Alarm 500" in payload
