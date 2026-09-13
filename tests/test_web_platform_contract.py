from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.config import Settings
from radmon.web_host import attach_web_routes, monitoring_url

ROOT = Path(__file__).resolve().parents[1]


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
    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    assert "@cloudflare/kumo" in package
    assert "@phosphor-icons/react" in package
    assert "Sidebar" in app
    assert "Viewer" in app and "Operator" in app and "Administrator" in app


def test_web_build_is_locked_and_node_is_build_time_only() -> None:
    assert (ROOT / "web/package-lock.json").is_file()
    package = (ROOT / "web/package.json").read_text(encoding="utf-8")
    assert '"build": "tsc -b && vite build"' in package
    assert '"start"' not in package
