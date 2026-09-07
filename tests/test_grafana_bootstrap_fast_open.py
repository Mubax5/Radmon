from dataclasses import replace

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import DASHBOARD_UIDS, PLAYLIST_UID, build_playlist_payload


def test_playlist_probe_accepts_actual_rotating_operations_playlist():
    bootstrap = GrafanaBootstrap(Settings())
    playlist = build_playlist_payload()
    bootstrap._request_json = lambda *args, **kwargs: playlist

    assert bootstrap._probe_playlist("http://localhost:3000") is True


def test_dashboard_probe_verifies_every_generated_dashboard_uid():
    bootstrap = GrafanaBootstrap(Settings())
    requested: list[str] = []

    def fake_request(url: str, **kwargs):
        uid = url.rsplit("/", 1)[-1]
        requested.append(uid)
        return {"dashboard": {"uid": uid}}

    bootstrap._request_json = fake_request

    assert bootstrap._probe_dashboard("http://localhost:3000") is True
    assert requested == list(DASHBOARD_UIDS)


def test_candidate_urls_scan_fallback_ports_for_existing_radmon_grafana():
    settings = replace(
        Settings(),
        grafana_url="http://localhost:3000",
        grafana_fallback_port=3300,
    )
    bootstrap = GrafanaBootstrap(settings)

    candidates = bootstrap._candidate_base_urls()

    assert "http://localhost:3300" in candidates
    assert "http://localhost:3301" in candidates
    assert "http://localhost:3302" in candidates


def test_ensure_reuses_existing_fallback_grafana_without_starting_new_services():
    settings = replace(
        Settings(),
        grafana_url="http://localhost:3000",
        grafana_fallback_port=3300,
    )
    launches: list[str] = []

    def never_native(**kwargs):
        launches.append("native")
        raise AssertionError("native Grafana must not start when an existing RadMon instance is ready")

    def never_compose(**kwargs):
        launches.append("docker")
        raise AssertionError("Docker must not start when an existing RadMon instance is ready")

    bootstrap = GrafanaBootstrap(
        settings,
        dashboard_probe=lambda base: base == "http://localhost:3302",
        playlist_probe=lambda base: base == "http://localhost:3302",
        grafana_health_probe=lambda base: False,
        native_runner=never_native,
        compose_runner=never_compose,
        sleeper=lambda _: None,
        attempts=1,
    )

    result = bootstrap.ensure()

    assert result.startswith(f"http://localhost:3302/playlists/play/{PLAYLIST_UID}")
    assert launches == []
