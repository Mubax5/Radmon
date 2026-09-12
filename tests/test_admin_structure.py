from pathlib import Path


def test_admin_source_contains_legacy_workflow_tabs():
    source = Path("radmon/admin/main_window.py").read_text(encoding="utf-8")
    for tab in ("Recent", "Tabular", "Chart", "Reports", "Alarm", "Logs"):
        assert tab in source


def test_admin_pages_are_split_by_responsibility():
    for name in ("recent_page", "tabular_page", "chart_page", "reports_page", "alarm_page", "logs_page"):
        assert Path(f"radmon/admin/{name}.py").is_file()


def test_production_entrypoint_owns_central_and_desktop_lifecycle():
    package_main = Path("radmon/__main__.py").read_text(encoding="utf-8")
    production = Path("radmon/production_app.py").read_text(encoding="utf-8")
    assert "from .production_app import main" in package_main
    assert "CentralService" in production
    assert "run_admin_ui" in production
    assert "SingleInstanceLock" in production
    assert "--source" not in production


def test_developer_entrypoint_owns_detector_runtime_only():
    source = Path("radmon/dev_app.py").read_text(encoding="utf-8")
    assert "QApplication" in source
    assert "ReportService" in source
    assert "MainWindow" in source
    assert "ApplicationRuntime" in source
    assert 'choices=("detector", "dummy")' in source
