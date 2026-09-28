from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QDateTime
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from radmon.admin.chart_page import ChartPage
from radmon.admin.icons import app_icon
from radmon.admin.reports_page import ReportsPage
from radmon.config import Settings
from radmon.reports import ReportService


class FakeRepo:
    def station_config(self, serid=None):
        from radmon.models import StationConfig

        return StationConfig(5202, "52", "IS-1 Koridor", "Gd.52", 8, 10, 5, "uSv/h")

    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return [
            {
                "serid": 5202,
                "dtom": start,
                "doserate": 0.10,
                "dose": 0.0,
                "previnterval": 2,
                "stat": 0,
            },
            {
                "serid": 5202,
                "dtom": min(end, start + timedelta(seconds=2)),
                "doserate": 0.12,
                "dose": 0.000061,
                "previnterval": 2,
                "stat": 0,
            },
        ]

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return []


def app():
    return QApplication.instance() or QApplication([])


def test_semantic_tabler_qicons_load_from_vendored_svgs():
    app()
    for slot in (
        "recent", "tabular", "chart", "reports", "alarm", "monitoring",
        "station_group", "detector", "suppress_alarm",
    ):
        assert not app_icon(slot).isNull(), slot


def test_chart_page_constructs_and_refreshes_offscreen():
    app()
    page = ChartPage(FakeRepo(), Settings().for_dummy())
    page.refresh_live()
    assert page.rate_curve is not None
    assert page.dose_curve is not None
    assert len(page.points) == 2


def test_desktop_pdf_export_uses_report_service_artifact_bytes(tmp_path: Path, monkeypatch):
    app()
    settings = Settings(report_dir=tmp_path).for_dummy()
    page = ReportsPage(ReportService(FakeRepo(), settings), settings)
    page.start.setDateTime(QDateTime.fromString("2026-09-07 08:00:00", "yyyy-MM-dd HH:mm:ss"))
    page.end.setDateTime(QDateTime.fromString("2026-09-07 09:00:00", "yyyy-MM-dd HH:mm:ss"))
    page.build_preview()
    assert page.preview_ready

    from PySide6.QtWidgets import QMessageBox

    generated = b"%PDF-shared-report-service-artifact"
    calls = []

    def export_pdf(start, end, destination):
        calls.append((start, end))
        destination.write_bytes(generated)
        return destination

    monkeypatch.setattr(page.report_service, "export_pdf", export_pdf)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: pytest.fail(str(args)))
    page.export_pdf()

    destination = next(tmp_path.glob("radmon-5202-*_to_*.pdf"))
    assert destination.read_bytes() == generated
    assert calls == [page.range()]
