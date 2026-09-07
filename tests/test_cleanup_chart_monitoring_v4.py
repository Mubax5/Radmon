from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from radmon.admin.chart_page import chart_series_from_rows
from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import PLAYLIST_UID


def test_chart_uses_database_values_without_reintegrating_dose() -> None:
    start = datetime(2026, 9, 7, 17, 0, 0)
    rows = [
        {"dtom": start, "doserate": 0.21, "dose": 0.00012, "stat": 0},
        {"dtom": start + timedelta(seconds=2), "doserate": 0.23, "dose": 0.00013, "stat": 0},
    ]
    x, rates, doses, stats = chart_series_from_rows(rows)
    assert rates == [0.21, 0.23]
    assert doses == [0.00012, 0.00013]
    assert stats == [0, 0]
    assert x[1] > x[0]


def test_chart_visual_selector_supports_operator_friendly_views() -> None:
    source = Path("radmon/admin/chart_page.py").read_text(encoding="utf-8")
    for label in ("Trend", "Status Pie", "Threshold Progress"):
        assert label in source
    assert "QComboBox" in source
    assert "QProgressBar" in source
    assert "QPainter" in source
    assert "BarGraphItem" not in source


def test_reports_default_to_dedicated_report_directory() -> None:
    settings = Settings()
    assert settings.report_dir == Path("!REPORT!")
    source = Path("radmon/admin/reports_page.py").read_text(encoding="utf-8")
    assert "self.settings.report_dir" in source
    assert "mkdir(parents=True, exist_ok=True)" in source


def test_grafana_can_provision_an_existing_local_instance_before_fallbacks() -> None:
    calls: list[str] = []
    probe_count = {"value": 0}

    def probe(base: str) -> bool:
        probe_count["value"] += 1
        calls.append(f"probe:{base}")
        return probe_count["value"] >= 3

    bootstrap = GrafanaBootstrap(
        Settings(grafana_url="http://localhost:3000"),
        dashboard_probe=probe,
        playlist_probe=probe,
        grafana_health_probe=lambda base: base == "http://localhost:3000",
        api_provisioner=lambda base: calls.append(f"provision:{base}") or True,
        native_runner=lambda **_: calls.append("native"),
        compose_runner=lambda **_: calls.append("compose"),
        sleeper=lambda _: None,
        attempts=1,
    )

    url = bootstrap.ensure()
    assert url.startswith(f"http://localhost:3000/playlists/play/{PLAYLIST_UID}")
    assert "provision:http://localhost:3000" in calls
    assert "native" not in calls
    assert "compose" not in calls


def test_stale_configured_grafana_still_discovers_local_port_3000() -> None:
    calls: list[str] = []
    available = {"provisioned": False}

    def dashboard_probe(base: str) -> bool:
        return base == "http://localhost:3000" and available["provisioned"]

    def provision(base: str) -> bool:
        calls.append(f"provision:{base}")
        available["provisioned"] = True
        return True

    bootstrap = GrafanaBootstrap(
        Settings(grafana_url="http://localhost:3300"),
        dashboard_probe=dashboard_probe,
        playlist_probe=dashboard_probe,
        grafana_health_probe=lambda base: base == "http://localhost:3000",
        api_provisioner=provision,
        native_runner=lambda **_: calls.append("native"),
        compose_runner=lambda **_: calls.append("compose"),
        sleeper=lambda _: None,
        attempts=1,
    )

    url = bootstrap.ensure()
    assert url.startswith(f"http://localhost:3000/playlists/play/{PLAYLIST_UID}")
    assert calls == ["provision:http://localhost:3000"]


def test_dummy_defaults_to_normal_readings_but_keeps_mode_configurable() -> None:
    settings = Settings()
    assert settings.dummy_mode == "normal"
    source = Path("radmon/runtime.py").read_text(encoding="utf-8")
    assert "self.settings.dummy_mode" in source


def test_internal_planning_artifacts_are_not_kept_in_repo() -> None:
    assert not Path("docs/superpowers").exists()
