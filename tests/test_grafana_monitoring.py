import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from radmon.admin import main_window as main_window_module
from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import (
    DASHBOARD_UIDS,
    OPERATIONS_PAGE_UIDS,
    PAGE_UIDS,
    PLAYLIST_UID,
    build_dashboard_payloads,
    build_playlist_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_python_runtime_no_longer_hosts_public_monitoring():
    runtime = read("radmon/runtime.py")
    assert "create_public_app" not in runtime
    assert "uvicorn" not in runtime
    assert "radmon-public" not in runtime


def test_settings_and_admin_open_verified_grafana_monitoring():
    config = read("radmon/config.py")
    main_window = read("radmon/admin/main_window.py")
    assert "grafana_url" in config
    assert "grafana_fallback_port" in config
    assert "RADMON_GRAFANA_URL" in config
    assert "RADMON_GRAFANA_PORT" in config
    assert "GrafanaBootstrap" in main_window
    assert "open_external_url" in main_window
    assert "self._grafana_ready_url" in main_window


def test_external_url_launcher_has_real_fallback_when_primary_opener_rejects():
    calls: list[tuple[str, str]] = []

    opened = main_window_module.open_external_url(
        "http://localhost:3000/playlists/play/radmon-tv",
        platform_name="posix",
        qt_open=lambda _url: calls.append(("qt", "called")) or False,
        browser_open=lambda url: calls.append(("browser", url)) or True,
    )

    assert opened is True
    assert calls == [
        ("qt", "called"),
        ("browser", "http://localhost:3000/playlists/play/radmon-tv"),
    ]


def test_windows_monitoring_launcher_prefers_native_default_browser():
    calls: list[tuple[str, str]] = []

    opened = main_window_module.open_external_url(
        "http://localhost:3000/playlists/play/radmon-tv",
        platform_name="nt",
        native_open=lambda url: calls.append(("native", url)),
        qt_open=lambda _url: calls.append(("qt", "called")) or False,
        browser_open=lambda url: calls.append(("browser", url)) or True,
    )

    assert opened is True
    assert calls == [("native", "http://localhost:3000/playlists/play/radmon-tv")]


def test_monitoring_click_always_retries_setup_and_uses_dedicated_poll_timer():
    source = read("radmon/admin/main_window.py")
    start = source.index("    def open_monitoring")
    end = source.index("    def _open_monitoring_if_ready", start)
    block = source[start:end]

    assert "if self._grafana_error:" not in block
    assert "self._start_grafana_bootstrap()" in block
    assert "self._monitoring_poll_timer.start()" in block
    assert "open_external_url(" in source


def test_refresh_status_does_not_hide_monitoring_setup_feedback():
    source = read("radmon/admin/main_window.py")
    start = source.index("    def refresh_current_page")
    block = source[start:]
    assert "if self._monitoring_open_pending:" in block
    assert "Grafana sedang disiapkan" in block


def test_docker_compose_bootstrap_has_hard_timeout(tmp_path, monkeypatch):
    grafana_dir = tmp_path / "grafana"
    grafana_dir.mkdir()
    (grafana_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    bootstrap = GrafanaBootstrap(Settings(), project_root=tmp_path)
    bootstrap._run_compose(env={})

    assert 1 <= int(captured["timeout"]) <= 30


def test_docker_compose_timeout_becomes_actionable_runtime_error(tmp_path, monkeypatch):
    grafana_dir = tmp_path / "grafana"
    grafana_dir.mkdir()
    (grafana_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    bootstrap = GrafanaBootstrap(Settings(), project_root=tmp_path)

    with pytest.raises(RuntimeError, match="timeout"):
        bootstrap._run_compose(env={})


def test_bootstrap_reuses_ready_fallback_before_starting_services():
    settings = replace(Settings(), grafana_url="http://localhost:3000", grafana_fallback_port=3300)
    compose_calls: list[dict] = []
    native_calls: list[dict] = []

    def probe(base_url: str) -> bool:
        return base_url == "http://localhost:3300"

    def compose_runner(*, env):
        compose_calls.append(dict(env))

    def native_runner(**kwargs):
        native_calls.append(dict(kwargs))

    bootstrap = GrafanaBootstrap(
        settings,
        dashboard_probe=probe,
        playlist_probe=probe,
        grafana_health_probe=lambda base: base == "http://localhost:3300",
        api_provisioner=lambda base: True,
        native_runner=native_runner,
        compose_runner=compose_runner,
        sleeper=lambda _: None,
        attempts=2,
    )
    result = bootstrap.ensure()

    assert compose_calls == []
    assert native_calls == []
    assert result.startswith(f"http://localhost:3300/playlists/play/{PLAYLIST_UID}")
    assert "kiosk=1" in result and "autofitpanels" in result


def test_bootstrap_refuses_to_return_unverified_playlist():
    bootstrap = GrafanaBootstrap(
        replace(Settings(), grafana_fallback_port=3300),
        dashboard_probe=lambda base_url: False,
        playlist_probe=lambda base_url: False,
        compose_runner=lambda **kwargs: None,
        sleeper=lambda _: None,
        attempts=2,
    )
    try:
        bootstrap.ensure()
    except RuntimeError as exc:
        assert "playlist" in str(exc).lower()
    else:
        raise AssertionError("unverified Grafana playlist must not be returned")


def test_grafana_tv_uses_three_logical_pages_with_eight_operations_variants():
    dashboards = build_dashboard_payloads()
    assert len(PAGE_UIDS) == 3
    assert len(OPERATIONS_PAGE_UIDS) == 8
    assert len(dashboards) == 10
    assert [dashboard["uid"] for dashboard in dashboards] == list(DASHBOARD_UIDS)
    for dashboard in dashboards:
        assert dashboard["refresh"] == "2s"
        assert dashboard["timezone"] == "browser"
        assert dashboard["templating"]["list"] == []

    playlist_values = [item["value"] for item in build_playlist_payload()["spec"]["items"]]
    assert len(playlist_values) == 24
    for cycle in range(8):
        assert playlist_values[cycle * 3] == PAGE_UIDS[0]
        assert playlist_values[cycle * 3 + 1] == PAGE_UIDS[1]
        assert playlist_values[cycle * 3 + 2] == OPERATIONS_PAGE_UIDS[cycle]

    payload = json.dumps(dashboards, ensure_ascii=False)
    for table in ("device", "measurement", "alarm"):
        assert table in payload
    assert " recent " not in payload.lower()
    assert "radmon_" not in payload
    assert "REAL TIME DOSE RATE MONITORING SYSTEM" in payload
    assert "µSv/h" in payload
    assert "Dose Rate · Gedung" in payload
    assert "Kondisi Operasional Detector · Page 8/8" in payload


def test_grafana_provisioning_uses_mysql_and_collision_safe_bundled_port():
    datasource = read("grafana/provisioning/datasources/ipradmon.yaml")
    compose = read("grafana/docker-compose.yml")
    assert "type: mysql" in datasource
    assert "database: ipradmon" in datasource
    assert "RADMON_DB" in datasource
    assert '${RADMON_GRAFANA_PORT:-3300}:3000' in compose
    assert "GF_AUTH_ANONYMOUS_ENABLED" in compose
    assert "GF_AUTH_ANONYMOUS_ORG_ROLE" in compose
    assert "/var/lib/grafana/dashboards" not in compose
    assert not (ROOT / "grafana/provisioning/dashboards/radmon.yaml").exists()


def test_grafana_owns_public_monitoring_and_queries_alarm_table_explicitly():
    assert not (ROOT / "radmon/public_api.py").exists()
    assert not (ROOT / "monitoring").exists()
    payload = json.dumps(build_dashboard_payloads()[2])
    assert "FROM alarm" in payload or "FROM `alarm`" in payload


def test_tv_pages_have_no_operator_variables():
    for dashboard in build_dashboard_payloads():
        assert dashboard["templating"]["list"] == []
