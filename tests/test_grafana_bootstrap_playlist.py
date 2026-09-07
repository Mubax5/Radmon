from pathlib import Path

from radmon.config import Settings
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.grafana_tv import PAGE_UIDS, PLAYLIST_UID


def test_bootstrap_requires_playlist_and_returns_playlist_kiosk_url(tmp_path):
    provisioned = {"value": False}
    calls = []

    def dashboard_probe(base):
        calls.append(f"dashboard:{base}")
        return provisioned["value"]

    def playlist_probe(base):
        calls.append(f"playlist:{base}")
        return provisioned["value"]

    def provision(base):
        calls.append(f"provision:{base}")
        provisioned["value"] = True
        return True

    bootstrap = GrafanaBootstrap(
        Settings(grafana_url="http://localhost:3000"),
        project_root=tmp_path,
        dashboard_probe=dashboard_probe,
        playlist_probe=playlist_probe,
        grafana_health_probe=lambda base: base == "http://localhost:3000",
        api_provisioner=provision,
        native_runner=lambda **_: None,
        compose_runner=lambda **_: None,
        sleeper=lambda _: None,
        attempts=1,
    )
    url = bootstrap.ensure()
    assert calls.count("provision:http://localhost:3000") == 1
    assert f"/playlists/play/{PLAYLIST_UID}" in url
    assert "kiosk=1" in url and "autofitpanels" in url


def test_api_provisioner_upserts_eight_dashboards_and_playlist(tmp_path):
    bootstrap = GrafanaBootstrap(Settings(), project_root=tmp_path)
    calls = []

    def request(url, *, method="GET", payload=None, use_auth=True):
        calls.append((method, url, payload))
        if "/api/datasources/uid/" in url and method == "GET":
            return {"uid": "ipradmon-mysql"}
        if "/apis/playlist.grafana.app/" in url and method == "GET":
            raise RuntimeError("404")
        return {}

    bootstrap._request_json = request
    assert bootstrap._provision_via_api("http://localhost:3000") is True
    dashboard_posts = [call for call in calls if call[0] == "POST" and call[1].endswith("/api/dashboards/db")]
    assert len(dashboard_posts) == 8
    assert [call[2]["dashboard"]["uid"] for call in dashboard_posts] == list(PAGE_UIDS)
    playlist_posts = [call for call in calls if call[0] == "POST" and "/apis/playlist.grafana.app/" in call[1]]
    assert len(playlist_posts) == 1
    assert playlist_posts[0][2]["metadata"]["name"] == PLAYLIST_UID
    assert playlist_posts[0][2]["spec"]["interval"] == "10s"
    assert len(playlist_posts[0][2]["spec"]["items"]) == 8


def test_api_provisioner_updates_existing_playlist_with_resource_version(tmp_path):
    bootstrap = GrafanaBootstrap(Settings(), project_root=tmp_path)
    calls = []

    def request(url, *, method="GET", payload=None, use_auth=True):
        calls.append((method, url, payload))
        if "/api/datasources/uid/" in url and method == "GET":
            return {"uid": "ipradmon-mysql"}
        if "/apis/playlist.grafana.app/" in url and method == "GET":
            return {"metadata": {"name": PLAYLIST_UID, "resourceVersion": "77"}}
        return {}

    bootstrap._request_json = request
    bootstrap._provision_via_api("http://localhost:3000")
    puts = [call for call in calls if call[0] == "PUT" and "/apis/playlist.grafana.app/" in call[1]]
    assert len(puts) == 1
    assert puts[0][2]["metadata"]["resourceVersion"] == "77"
