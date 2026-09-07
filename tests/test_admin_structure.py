from pathlib import Path


def test_admin_source_contains_legacy_workflow_tabs():
    source = Path("radmon/admin/main_window.py").read_text(encoding="utf-8")
    for tab in ("Recent", "Tabular", "Chart", "Reports", "Alarm", "Logs"):
        assert tab in source


def test_admin_pages_are_split_by_responsibility():
    for name in ("recent_page", "tabular_page", "chart_page", "reports_page", "alarm_page", "logs_page"):
        assert Path(f"radmon/admin/{name}.py").is_file()


def test_admin_entrypoint_uses_pyside6_and_report_service():
    source = Path("admin_app.py").read_text(encoding="utf-8")
    assert "PySide6" in source
    assert "ReportService" in source
    assert "MainWindow" in source
