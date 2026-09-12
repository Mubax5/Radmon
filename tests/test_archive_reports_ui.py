from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reports_page_exposes_archive_inventory_without_auto_preview():
    source = (ROOT / "radmon/admin/reports_page.py").read_text(encoding="utf-8")
    assert "QComboBox" in source
    assert "archive_catalog" in source
    assert '"Active"' in source
    assert '"Archive"' in source
    assert "_archive_selection_changed" in source
    handler = source.split("def _archive_selection_changed", 1)[1].split("\n    def ", 1)[0]
    assert "build_preview" not in handler


def test_main_window_passes_archive_catalog_to_reports_page():
    source = (ROOT / "radmon/admin/main_window.py").read_text(encoding="utf-8")
    assert "archive_catalog=None" in source
    assert "archive_catalog=archive_catalog" in source


def test_lan_desktop_uses_composite_repository_for_active_and_archived_reports():
    source = (ROOT / "radmon/desktop_app.py").read_text(encoding="utf-8")
    assert "ArchiveReportRepository" in source
    assert "CompositeReportRepository" in source
    assert "archive_catalog=archive_catalog" in source
