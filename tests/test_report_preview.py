from datetime import datetime, timedelta
from pathlib import Path

from radmon.config import Settings
from radmon.reports import ReportService

ROOT = Path(__file__).resolve().parents[1]


class FakeRepo:
    def station_config(self, serid=None):
        from radmon.models import StationConfig
        return StationConfig(5202, "52", "IS-1 Koridor", "Gd.52", 8, 10, 5, "uSv/h")

    def measurement_history(self, start, end, *, serid=None, limit=5000):
        return [
            {"serid": 5202, "dtom": start, "doserate": 0.1, "dose": 0.0, "previnterval": 2, "stat": 0},
            {"serid": 5202, "dtom": start + timedelta(hours=1), "doserate": 0.2, "dose": 0.15, "previnterval": 2, "stat": 0},
        ]

    def alarm_history(self, start=None, end=None, *, serid=None, limit=1000):
        return []


def test_preview_html_matches_dpfk_report_sections():
    start = datetime(2026, 9, 7, 8, 0, 0)
    end = start + timedelta(hours=1)
    html = ReportService(FakeRepo(), Settings().for_dummy()).preview_html(start, end)
    assert "Instalasi Pengelolaan Limbah Radioaktif" in html
    assert "Summary" in html
    assert "First Measurement" in html
    assert "Last Measurement" in html
    assert "Dose rate and Approx. Dose" in html
    assert "IS-1 Koridor" in html
    assert "0.150000" in html


def test_reports_page_is_preview_first_and_prints_same_document():
    source = (ROOT / "radmon/admin/reports_page.py").read_text(encoding="utf-8")
    assert "QTextBrowser" in source
    assert 'QPushButton("Preview")' in source
    assert "self.print_button.setEnabled(False)" in source
    assert "self.pdf_button.setEnabled(False)" in source
    assert "self.preview.setHtml" in source
    assert "self.preview.document()" in source
    assert "QPrintDialog" in source
    assert "QPrinter.PdfFormat" in source


def test_preview_reuses_one_measurement_snapshot_for_summary_and_detail():
    class CountingRepo(FakeRepo):
        def __init__(self):
            self.calls = 0

        def measurement_history(self, start, end, *, serid=None, limit=5000):
            self.calls += 1
            return super().measurement_history(start, end, serid=serid, limit=limit)

    start = datetime(2026, 9, 7, 8, 0, 0)
    end = start + timedelta(hours=1)
    repo = CountingRepo()
    ReportService(repo, Settings().for_dummy()).preview_html(start, end)
    assert repo.calls == 1
