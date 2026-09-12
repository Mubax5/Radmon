from __future__ import annotations

from pathlib import Path

from radmon.config import Settings
from radmon.grafana_tv import build_dashboard_payloads

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_has_one_package_entrypoint_and_no_batch_launchers():
    assert list(ROOT.glob("*.bat")) == []
    package_main = read("radmon/__main__.py")
    assert "from .production_app import main" in package_main
    assert "raise SystemExit(main())" in package_main


def test_developer_runtime_exposes_detector_and_dummy_only():
    source = read("radmon/dev_app.py")
    parser_body = source.split("def parser", 1)[1].split("def run_developer_mode", 1)[0]
    assert 'choices=("detector", "dummy")' in parser_body
    assert '"lan"' not in parser_body
    assert "SingleInstanceLock" in source


def test_default_runtime_matches_station_catalog_and_dummy_selects_5202(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("RADMON_"):
            monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.serid == 5201
    assert settings.room == "IS-1"
    assert settings.location == "Gd.52"
    assert settings.warnlevel == 23.0
    assert settings.alarmlevel == 25.0
    assert settings.unit == "µSv/h"
    assert settings.refresh_interval == 2.0
    assert settings.sync_enabled is False
    dummy = settings.for_dummy()
    assert dummy.serid == 5202
    assert dummy.room == "IS-1 Koridor"
    assert dummy.sample_interval == 2.0


def test_all_live_admin_refresh_is_driven_by_one_two_second_timer():
    main_window = read("radmon/admin/main_window.py")
    assert "self.refresh_timer.start(2000)" in main_window
    assert "currentWidget" in main_window
    for page in ("recent_page.py", "tabular_page.py", "chart_page.py", "reports_page.py", "alarm_page.py", "logs_page.py"):
        source = read(f"radmon/admin/{page}")
        assert ".start(3000)" not in source
        assert ".start(5000)" not in source


def test_background_refresh_never_opens_modal_error_popups():
    for page in ("recent_page.py", "tabular_page.py", "chart_page.py", "reports_page.py", "alarm_page.py", "logs_page.py"):
        source = read(f"radmon/admin/{page}")
        if "def refresh_live" in source:
            refresh_body = source.split("def refresh_live", 1)[1].split("\n    def ", 1)[0]
            assert "QMessageBox" not in refresh_body


def test_public_monitoring_is_grafana_tv_playlist_with_two_second_refresh():
    assert not (ROOT / "radmon/public_api.py").exists()
    assert not (ROOT / "monitoring").exists()
    for dashboard in build_dashboard_payloads():
        assert dashboard["refresh"] == "2s"
        assert dashboard["templating"]["list"] == []
    runtime = read("radmon/runtime.py")
    assert "uvicorn" not in runtime
    assert "create_public_app" not in runtime


def test_sync_uses_measurement_checkpoint_instead_of_database_queue():
    source = read("radmon/sync.py")
    assert "measurements_after" in source
    assert "SyncCheckpointStore" in source
    assert "pending_sync" not in source
    assert "mark_sync_sent" not in source
    assert "radmon_sync_queue" not in source


def test_central_ingest_is_idempotent_via_measurement_primary_key_only():
    source = read("radmon/central_api.py")
    assert "INSERT IGNORE INTO measurement" in source
    assert "radmon_sync_receipt" not in source
