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
        return [{"eventid": 1, "state": "ALERT", "severity": "warning", "started_at": start, "ended_at": end, "last_value": 8.5, "threshold_value": 8.0, "acknowledged_by": "operator-a", "acknowledgement_note": "checked"}]


def test_report_summary_calculates_min_avg_max_and_trapezoid_dose():
    start = datetime(2026, 9, 7, 8, 0, 0); end = start + timedelta(hours=2); service = ReportService(FakeRepo(), Settings()); summary = service.summary(start, end)
    assert summary.minimum == pytest.approx(0.1); assert summary.average == pytest.approx(0.2); assert summary.maximum == pytest.approx(0.3)
    assert summary.sample_count == 3; assert summary.approximate_dose == pytest.approx(0.4); assert summary.first_measurement == start; assert summary.last_measurement == end


def test_csv_export_contains_measurements(tmp_path):
    start = datetime(2026, 9, 7, 8, 0, 0); end = start + timedelta(hours=2); service = ReportService(FakeRepo(), Settings()); path = service.export_csv(start, end, tmp_path / "history.csv"); content = path.read_text(encoding="utf-8")
    assert "serid,dtom,doserate" in content and "5202" in content and "0.3" in content


def test_pdf_export_has_pdf_signature_and_station_identity(tmp_path):
    start = datetime(2026, 9, 7, 8, 0, 0); end = start + timedelta(hours=2); service = ReportService(FakeRepo(), Settings()); path = service.export_pdf(start, end, tmp_path / "report.pdf"); payload = path.read_bytes()
    assert payload.startswith(b"%PDF") and len(payload) > 1000
