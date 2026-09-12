from __future__ import annotations

from pathlib import Path

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import PLAYLIST_UID

ROOT = Path(__file__).resolve().parents[1]


def test_grafana_uses_native_install_before_docker_when_local_api_cannot_be_provisioned(monkeypatch) -> None:
    calls: list[str] = []
    native_started = {"value": False}

    def dashboard_probe(base: str) -> bool:
        return base == "http://localhost:3300" and native_started["value"]

    def health_probe(base: str) -> bool:
        return base == "http://localhost:3300" and native_started["value"]

    def native_runner(*, env, port: int) -> None:
        calls.append(f"native:{port}")
        native_started["value"] = True

    # This test verifies native-before-Docker ordering, not host port availability.
    # Keep the port deterministic so a running production Grafana on 3300/3301
    # cannot turn the test into an environment-dependent false negative.
    monkeypatch.setattr(
        GrafanaBootstrap,
        "_find_free_port",
        lambda self, preferred: preferred,
    )

    bootstrap = GrafanaBootstrap(
        Settings(grafana_fallback_port=3300),
        dashboard_probe=dashboard_probe,
        playlist_probe=dashboard_probe,
        grafana_health_probe=health_probe,
        api_provisioner=lambda base: calls.append(f"provision:{base}") or True,
        native_runner=native_runner,
        compose_runner=lambda **_: (_ for _ in ()).throw(AssertionError("Docker must be last fallback")),
        sleeper=lambda _: None,
        attempts=2,
    )

    url = bootstrap.ensure()
    assert calls[0] == "native:3300"
    assert "provision:http://localhost:3300" in calls
    assert url.startswith(f"http://localhost:3300/playlists/play/{PLAYLIST_UID}")


def test_chart_metrics_make_status_pie_and_threshold_progress_meaningful() -> None:
    from radmon.admin.chart_metrics import status_breakdown, threshold_progress

    rates = [0.2, 0.3, 8.2, 10.5]
    assert status_breakdown(rates, warnlevel=8.0, alarmlevel=10.0) == {
        "NORMAL": 2,
        "ALERT": 1,
        "ALARM": 1,
    }

    metrics = threshold_progress(rates, alarmlevel=10.0)
    assert metrics["current_value"] == 10.5
    assert metrics["average_value"] == 4.8
    assert metrics["peak_value"] == 10.5
    assert metrics["current_percent"] == 100.0
    assert metrics["average_percent"] == 48.0
    assert metrics["peak_percent"] == 100.0


def test_chart_page_uses_pie_and_progress_views_instead_of_bar_graphs() -> None:
    source = (ROOT / "radmon/admin/chart_page.py").read_text(encoding="utf-8")
    assert "Status Pie" in source
    assert "Threshold Progress" in source
    assert "QProgressBar" in source
    assert "QPainter" in source
    assert "BarGraphItem" not in source
    assert "Dose Rate Distribution" not in source
    assert "Status Distribution" not in source
