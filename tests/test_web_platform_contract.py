import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.config import Settings
from radmon.web_host import attach_web_routes, monitoring_url

ROOT = Path(__file__).resolve().parents[1]


def _frontend_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "web/src").rglob("*.tsx")
    )


def test_monitoring_landing_is_grafana_only_redirect(tmp_path: Path) -> None:
    app = FastAPI()
    settings = Settings(central_host="192.168.1.2", grafana_fallback_port=3300)
    attach_web_routes(app, settings=settings, web_dist=tmp_path / "missing")

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == monitoring_url(settings)
    assert "3300" in response.headers["location"]
    assert "kiosk" in response.headers["location"].lower()


def test_web_app_returns_clear_503_when_build_is_missing(tmp_path: Path) -> None:
    app = FastAPI()
    attach_web_routes(app, settings=Settings(), web_dist=tmp_path / "missing")

    response = TestClient(app).get("/app")

    assert response.status_code == 503
    assert "web interface" in response.text.lower()


def test_frontend_sources_use_cloudflare_kumo_and_have_no_public_signin_overlay() -> None:
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    combined = _frontend_sources()
    assert "@cloudflare/kumo" in package
    assert "@phosphor-icons/react" in package
    assert "Viewer" in combined and "Operator" in combined and "Administrator" in combined


def test_web_build_is_locked_and_node_is_build_time_only() -> None:
    assert (ROOT / "web/package-lock.json").is_file()
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    assert '"build": "tsc -b && vite build"' in package
    assert '"start"' not in package


def test_web_control_plane_is_split_into_focused_modules() -> None:
    expected = [
        "web/src/auth.tsx",
        "web/src/layout.tsx",
        "web/src/pages/OverviewPage.tsx",
        "web/src/pages/StationsPage.tsx",
        "web/src/pages/HistoryPage.tsx",
        "web/src/pages/ArchivesPage.tsx",
        "web/src/pages/AlarmsPage.tsx",
        "web/src/pages/UsersPage.tsx",
        "web/src/pages/SystemPage.tsx",
    ]
    for relative in expected:
        assert (ROOT / relative).is_file(), relative

    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    assert "AuthProvider" in app
    assert "AppLayout" in app
    for page in (
        "OverviewPage",
        "StationsPage",
        "HistoryPage",
        "ArchivesPage",
        "AlarmsPage",
        "UsersPage",
        "SystemPage",
    ):
        assert f"function {page}" not in app


def test_web_uses_kumo_as_primary_component_system_without_browser_secret_storage() -> None:
    combined = _frontend_sources()
    assert "@cloudflare/kumo" in combined
    for forbidden in ("material-ui", "@mui/", "antd", "bootstrap"):
        assert forbidden not in combined.lower()
    assert "localStorage" not in combined
    assert "sessionStorage" not in combined


def test_sensitive_alarm_actions_use_kumo_dialogs_and_native_kumo_selects() -> None:
    actions = (ROOT / "web/src/Actions.tsx").read_text(encoding="utf-8")
    combined = _frontend_sources()
    assert "Dialog.Root" in actions
    assert "Dialog.Trigger" in actions
    assert "Dialog.Close" in actions
    assert "<Select" in actions
    assert re.search(r"<select(?:\s|>)", combined) is None
