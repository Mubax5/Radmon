from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.security import Role, SecurityStore
from radmon.web_api import attach_web_api_routes
from radmon.secure_api import SESSION_COOKIE


class FakeRepository:
    def stations(self):
        return [
            {"serid": 5201, "name": "IS-1", "location": "Gd.52", "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "uSv/h"},
            {"serid": 5202, "name": "IS-1 Koridor", "location": "Gd.52", "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "uSv/h"},
        ]

    def latest(self, serid: int):
        if serid == 5201:
            return {"serid": 5201, "dtom": "2026-09-13T04:00:00", "doserate": 10.0, "dose": 1.0, "previnterval": 2, "stat": 0}
        return {"serid": 5202, "dtom": "2026-09-13T04:00:00", "doserate": 26.0, "dose": 1.0, "previnterval": 2, "stat": 0}

    def history(self, serid: int, limit: int = 240):
        return [{"serid": serid, "dtom": "2026-09-13T04:00:00", "doserate": 10.0, "dose": 1.0, "previnterval": 2, "stat": 0}][:limit]


class FakeSourceHealth:
    def list_states(self):
        return [{"source_id": "gd50", "state": "CONNECTED"}]


def make_client(tmp_path, role: Role):
    security = SecurityStore(tmp_path / f"{role.value}.db")
    username = role.value.lower()
    security.create_user(username, role.value, role, "Password123!", "2468")
    token = security.create_session(username, 3600)
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=FakeRepository(), source_health=FakeSourceHealth())
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    return client


def test_anonymous_is_not_a_viewer(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=FakeRepository())
    response = TestClient(app).get("/api/v1/web/overview")
    assert response.status_code == 401


def test_authenticated_viewer_can_read_overview_and_history(tmp_path):
    client = make_client(tmp_path, Role.VIEWER)
    overview = client.get("/api/v1/web/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["role"] == "Viewer"
    assert body["counts"]["normal"] == 1
    assert body["counts"]["alarm"] == 1
    assert {item["serid"] for item in body["stations"]} == {5201, 5202}

    history = client.get("/api/v1/web/stations/5201/history?limit=50")
    assert history.status_code == 200
    assert history.json()[0]["serid"] == 5201


def test_system_diagnostics_are_administrator_only(tmp_path):
    viewer = make_client(tmp_path, Role.VIEWER)
    assert viewer.get("/api/v1/web/system").status_code == 403

    admin = make_client(tmp_path, Role.ADMINISTRATOR)
    response = admin.get("/api/v1/web/system")
    assert response.status_code == 200
    assert response.json()["sources"] == [{"source_id": "gd50", "state": "CONNECTED"}]
    assert response.json()["grafana_admin_url"] == "http://localhost:3300"
