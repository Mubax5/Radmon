from pathlib import Path
import socket

import pytest

from radmon.config import Settings
from radmon.grafana_persistent import PersistentGrafanaBootstrap
from radmon.grafana_tv import DASHBOARD_UIDS, PLAYLIST_UID


def test_existing_grafana_refreshes_datasource_credentials_without_overwriting_saved_resources(tmp_path: Path) -> None:
    settings = Settings(
        db_host="127.0.0.1",
        db_port=3306,
        db_user="radmon_reader",
        db_password="current-secret",
        db_name="ipradmon",
    )
    bootstrap = PersistentGrafanaBootstrap(settings, project_root=tmp_path)
    writes: list[tuple[str, str, dict]] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            return {"status": "OK", "message": "Database Connection OK"}
        if "/api/datasources/uid/" in url:
            return {"uid": "ipradmon-mysql", "name": "ipradmon"}
        if "/api/dashboards/uid/" in url:
            return {"dashboard": {"uid": url.rsplit("/", 1)[-1], "editable": True, "panels": [{"id": 99}]}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID, "resourceVersion": "42"}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    assert len(writes) == 1
    method, url, payload = writes[0]
    assert method == "PUT"
    assert url.endswith("/api/datasources/uid/ipradmon-mysql")
    assert payload["url"] == "127.0.0.1:3306"
    assert payload["database"] == "ipradmon"
    assert payload["user"] == "radmon_reader"
    assert payload["secureJsonData"]["password"] == "current-secret"


def test_legacy_readonly_dashboard_is_unlocked_without_restoring_factory_layout(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    writes: list[dict] = []

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        if method != "GET":
            writes.append(payload or {})
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            return {"status": "OK", "message": "Database Connection OK"}
        if "/api/datasources/uid/" in url:
            return {"uid": "ipradmon-mysql"}
        if "/api/dashboards/uid/" in url:
            uid = url.rsplit("/", 1)[-1]
            return {"dashboard": {"uid": uid, "editable": False, "title": "Operator custom", "panels": [{"id": 777, "title": "Saved custom panel"}]}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_writes = [item for item in writes if "dashboard" in item]
    assert len(dashboard_writes) == len(DASHBOARD_UIDS)
    for item in dashboard_writes:
        assert item["overwrite"] is True
        assert item["dashboard"]["editable"] is True
        assert item["dashboard"]["title"] == "Operator custom"
        assert item["dashboard"]["panels"] == [{"id": 777, "title": "Saved custom panel"}]


def test_missing_grafana_resources_are_seeded_editable_without_overwrite(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(), project_root=tmp_path)
    posts: list[tuple[str, dict]] = []
    datasource_created = False

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        nonlocal datasource_created
        if method == "GET":
            if url.endswith("/api/datasources/uid/ipradmon-mysql/health") and datasource_created:
                return {"status": "OK", "message": "Database Connection OK"}
            raise RuntimeError("missing")
        posts.append((url, payload or {}))
        if method == "POST" and url.endswith("/api/datasources"):
            datasource_created = True
        return {"status": "ok"}

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    dashboard_posts = [p for u, p in posts if u.endswith("/api/dashboards/db")]
    assert len(dashboard_posts) == len(DASHBOARD_UIDS)
    assert all(p.get("overwrite") is False for p in dashboard_posts)
    assert all(p["dashboard"].get("editable") is True for p in dashboard_posts)
    assert any("/api/datasources" in u for u, _ in posts)
    assert any("/playlists" in u for u, _ in posts)


def test_native_grafana_is_loopback_only_and_persistent(tmp_path: Path) -> None:
    settings = Settings(runtime_dir=Path("runtime"), grafana_fallback_port=3300)
    env = PersistentGrafanaBootstrap(settings, project_root=tmp_path)._native_environment(3300)
    assert env["GF_SERVER_HTTP_ADDR"] == "127.0.0.1"
    assert env["GF_SERVER_HTTP_PORT"] == "3300"
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert env["GF_AUTH_DISABLE_LOGIN_FORM"] == "false"
    assert str(tmp_path / "runtime" / "grafana" / "data") in env["GF_PATHS_DATA"]


def test_grafana_never_silently_moves_away_from_port_3300(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(Settings(grafana_fallback_port=3300), project_root=tmp_path)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    occupied = int(blocker.getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match="tidak akan pindah port otomatis"):
            bootstrap._find_free_port(occupied)
    finally:
        blocker.close()


def test_unhealthy_existing_datasource_is_recreated_before_monitoring_is_declared_ready(tmp_path: Path) -> None:
    bootstrap = PersistentGrafanaBootstrap(
        Settings(db_host="127.0.0.1", db_password="current-secret"),
        project_root=tmp_path,
    )
    writes: list[tuple[str, str, dict]] = []
    health_checks = 0

    def request(url: str, *, method: str = "GET", payload=None, use_auth=True):
        nonlocal health_checks
        if method != "GET":
            writes.append((method, url, payload or {}))
            return {"status": "ok"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql/health"):
            health_checks += 1
            if health_checks == 1:
                return {"status": "ERROR", "message": "Database Connection Failed"}
            return {"status": "OK", "message": "Database Connection OK"}
        if url.endswith("/api/datasources/uid/ipradmon-mysql"):
            return {"uid": "ipradmon-mysql", "name": "ipradmon"}
        if "/api/dashboards/uid/" in url:
            uid = url.rsplit("/", 1)[-1]
            return {"dashboard": {"uid": uid, "editable": True}}
        if "/apis/playlist.grafana.app/" in url:
            return {"metadata": {"name": PLAYLIST_UID}}
        raise AssertionError(url)

    bootstrap._request_json = request  # type: ignore[method-assign]
    assert bootstrap._provision_via_api("http://localhost:3300") is True

    assert health_checks == 2
    assert any(method == "DELETE" and url.endswith("/api/datasources/uid/ipradmon-mysql") for method, url, _ in writes)
    recreated = [payload for method, url, payload in writes if method == "POST" and url.endswith("/api/datasources")]
    assert len(recreated) == 1
    assert recreated[0]["secureJsonData"]["password"] == "current-secret"
