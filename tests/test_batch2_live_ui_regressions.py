from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.config import Settings
from radmon.lan import parse_lan_sources
from radmon.secure_api import SESSION_COOKIE
from radmon.security import Role, SecurityStore
from radmon.web_api import attach_web_api_routes
from radmon.web_host import attach_web_routes


ROOT = Path(__file__).resolve().parents[1]


class StaleRepository:
    def stations(self):
        return [
            {
                "serid": 3801,
                "name": "Kolam",
                "location": "Gd. 38",
                "warnlevel": 23.0,
                "alarmlevel": 25.0,
                "maxidlemin": 30,
                "unit": "uSv/h",
            }
        ]

    def latest(self, serid: int):
        assert serid == 3801
        return {
            "serid": 3801,
            "dtom": datetime.now(timezone.utc) - timedelta(days=2),
            "doserate": 0.0,
            "dose": 0.0,
            "previnterval": 2,
            "stat": 0,
        }

    def history(self, serid: int, limit: int = 240):
        return []


def _viewer_client(tmp_path: Path) -> TestClient:
    security = SecurityStore(tmp_path / "viewer.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    token = security.create_session("viewer", 3600)
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=StaleRepository())
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    return client


def test_lan_sources_fall_back_to_primary_db_credentials_when_lan_credentials_are_blank(monkeypatch):
    monkeypatch.setenv(
        "RADMON_LAN_SOURCES",
        "server50@192.168.1.50;server52@192.168.1.52;server38@192.168.1.38",
    )
    monkeypatch.setenv("RADMON_LAN_DB_USER", "")
    monkeypatch.setenv("RADMON_LAN_DB_PASSWORD", "")
    monkeypatch.setenv("RADMON_DB_USER", "root")
    monkeypatch.setenv("RADMON_DB_PASSWORD", "central-secret")

    sources = parse_lan_sources()

    assert sources
    assert all(source.user == "root" for source in sources)
    assert all(source.password == "central-secret" for source in sources)


def test_overview_marks_two_day_old_measurement_offline_instead_of_normal(tmp_path):
    response = _viewer_client(tmp_path).get("/api/v1/web/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["offline"] == 1
    assert body["counts"]["normal"] == 0
    assert body["stations"][0]["status"] == "offline"


def test_spa_shell_is_never_cached_across_installer_upgrades(tmp_path):
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>RadMon</title>", encoding="utf-8")
    app = FastAPI()
    attach_web_routes(app, settings=Settings(), web_dist=dist)

    response = TestClient(app).get("/app")

    assert response.status_code == 200
    assert "no-store" in response.headers.get("cache-control", "").lower()


def test_control_plane_has_no_letter_r_badges_and_uses_curated_navigation_icons():
    auth = (ROOT / "web/src/auth.tsx").read_text(encoding="utf-8")
    layout_files = [
        ROOT / "web/src/layout.tsx",
        ROOT / "web/src/layout/DesktopShell.tsx",
        ROOT / "web/src/layout/MobileShell.tsx",
        ROOT / "web/src/layout/MobileMoreSheet.tsx",
    ]
    layout = "\n".join(path.read_text(encoding="utf-8") for path in layout_files)
    combined = auth + "\n" + layout

    assert re.search(r">\s*R\s*<", combined) is None
    assert "@phosphor-icons/react" in layout
    assert "nav-icon" in layout
    assert "brin-logo.png" in auth
    assert "brin-logo.png" in layout
