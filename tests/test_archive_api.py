from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore


class EmptyMirror:
    def list_alarms(self, limit=500):
        return []


class ArchiveCatalog:
    def list_archives(self, limit=100):
        return [{"quarter_id": "2026-Q3", "state": "COMPLETE"}]

    def recap(self, quarter_id):
        return [{"year": 2026, "month": 9, "serid": 5201, "sample_count": 2}]


class ArchiveService:
    def __init__(self):
        self.calls = []

    def retry(self, quarter_id):
        self.calls.append(quarter_id)
        return {"quarter_id": quarter_id, "state": "COMPLETE"}


class FakeAlarmControl:
    pass


class FakeDeviceAdmin:
    pass


def make_client(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    security.create_user("view", "Viewer", Role.VIEWER, "Password123!", "9999")
    audit = AuditTrail(security)
    service = ArchiveService()
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=audit,
        alarm_mirror=EmptyMirror(),
        alarm_control=FakeAlarmControl(),
        device_admin=FakeDeviceAdmin(),
        archive_catalog=ArchiveCatalog(),
        archive_service=service,
    )
    return TestClient(app), audit, service


def login(client, username):
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "Password123!"},
    )
    assert response.status_code == 200


def test_archive_inventory_requires_authentication_but_viewer_can_read(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/v1/control/archives").status_code == 401
    login(client, "view")
    response = client.get("/api/v1/control/archives")
    assert response.status_code == 200
    assert response.json()[0]["quarter_id"] == "2026-Q3"
    recap = client.get("/api/v1/control/archives/2026-Q3/recap")
    assert recap.status_code == 200
    assert recap.json()[0]["month"] == 9


def test_archive_retry_requires_administrator_pin_and_is_audited(tmp_path):
    client, audit, service = make_client(tmp_path)
    login(client, "view")
    assert client.post(
        "/api/v1/control/archives/2026-Q3/retry",
        json={"pin": "9999"},
    ).status_code == 403
    client.post("/auth/logout")
    login(client, "admin")
    denied = client.post(
        "/api/v1/control/archives/2026-Q3/retry",
        json={"pin": "0000"},
    )
    assert denied.status_code in {400, 403}
    ok = client.post(
        "/api/v1/control/archives/2026-Q3/retry",
        json={"pin": "2468"},
    )
    assert ok.status_code == 200
    assert service.calls == ["2026-Q3"]
    assert any(event["action"] == "ARCHIVE_MANUAL_RETRY" for event in audit.list_events())
