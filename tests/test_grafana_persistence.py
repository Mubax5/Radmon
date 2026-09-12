from pathlib import Path

from radmon.config import Settings
from radmon.grafana_persistent import PersistentGrafanaBootstrap
from radmon.grafana_tv import DASHBOARD_UIDS, PLAYLIST_UID


def test_existing_grafana_resources_are_never_overwritten(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    writes: list[tuple[str, str]] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if method != "GET":
            writes.append((method, url))
        if "/api/datasources/uid/" in url:
            return {"uid": "ipradmon-mysql"}
        if "/api/dashboards/uid/" in url:
            return {"dashboard": {"uid": url.rsplit("/", 1)[-1]}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID, "resourceVersion": "42"}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True
    assert writes == []


def test_missing_grafana_resources_are_seeded_without_overwrite(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    posts: list[tuple[str, dict]] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if method == "GET":
            raise RuntimeError("missing")
        posts.append((url, payload or {}))
        return {"status": "ok"}

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_posts = [p for u, p in posts if u.endswith("/api/dashboards/db")]
    assert len(dashboard_posts) == len(DASHBOARD_UIDS)
    assert all(p.get("overwrite") is False for p in dashboard_posts)
    assert any("/api/datasources" in u for u, _ in posts)
    assert any("/playlists" in u for u, _ in posts)


def test_native_grafana_is_lan_visible_and_persistent(tmp_path: Path) -> None:
    settings = Settings(runtime_dir=Path("runtime"), grafana_fallback_port=3300)
    env = PersistentGrafanaBootstrap(settings, project_root=tmp_path)._native_environment(3300)
    assert env["GF_SERVER_HTTP_ADDR"] == "0.0.0.0"
    assert env["GF_SERVER_HTTP_PORT"] == "3300"
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert str(tmp_path / "runtime" / "grafana" / "data") in env["GF_PATHS_DATA"]
