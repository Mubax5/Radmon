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
from radmon.admin.icons import silk_icon
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


def test_silk_qicons_load_from_vendored_pngs():
    app()
    for name in ("clock", "table", "chart_line", "report", "lock", "monitor"):
        assert not silk_icon(name).isNull()


def test_chart_page_constructs_and_refreshes_offscreen():
    app()
    page = ChartPage(FakeRepo(), Settings().for_dummy())
    page.refresh_live()
    assert page.rate_curve is not None
    assert page.dose_curve is not None
    assert len(page.points) == 2


def test_report_preview_document_can_render_pdf_without_external_viewer(tmp_path: Path):
    app()
    settings = Settings().for_dummy()
    page = ReportsPage(ReportService(FakeRepo(), settings), settings)
    page.start.setDateTime(QDateTime.fromString("2026-09-07 08:00:00", "yyyy-MM-dd HH:mm:ss"))
    page.end.setDateTime(QDateTime.fromString("2026-09-07 09:00:00", "yyyy-MM-dd HH:mm:ss"))
    page.build_preview()
    assert page.preview_ready

    destination = tmp_path / "preview.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(destination))
    page.preview.document().print_(printer)
    assert destination.read_bytes().startswith(b"%PDF")
