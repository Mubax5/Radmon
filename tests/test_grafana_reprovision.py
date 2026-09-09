from dataclasses import replace

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import PLAYLIST_UID


def test_ready_existing_grafana_is_reprovisioned_before_reuse():
    settings = replace(Settings(), grafana_url="http://localhost:3000", grafana_fallback_port=3300)
    provision_calls: list[str] = []
    compose_calls: list[dict] = []
    native_calls: list[dict] = []

    def probe(base_url: str) -> bool:
        return base_url == "http://localhost:3300"

    def provision(base_url: str) -> bool:
        provision_calls.append(base_url)
        return True

    bootstrap = GrafanaBootstrap(
        settings,
        dashboard_probe=probe,
        playlist_probe=probe,
        grafana_health_probe=lambda base: base == "http://localhost:3300",
        api_provisioner=provision,
        native_runner=lambda **kwargs: native_calls.append(kwargs),
        compose_runner=lambda **kwargs: compose_calls.append(kwargs),
        sleeper=lambda _: None,
        attempts=2,
    )

    result = bootstrap.ensure()

    assert provision_calls == ["http://localhost:3300"]
    assert compose_calls == []
    assert native_calls == []
    assert result.startswith(f"http://localhost:3300/playlists/play/{PLAYLIST_UID}")
