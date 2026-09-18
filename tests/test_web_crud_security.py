from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import SESSION_COOKIE, attach_secure_routes
from radmon.security import Role, SecurityStore


class DeviceAdmin:
    def update_station(self, identity, pin, serid, changes):
        return {"serid": serid, **changes}

    def create_station(self, identity, pin, serid, values):
        return {"serid": serid, **values}

    def delete_station(self, identity, pin, serid):
        return None


class AlarmControl:
    def ack(self, *args, **kwargs):
        return {}


class ReportJobs:
    def __init__(self, path):
        self.path = path
        path.write_bytes(b"%PDF-test")

    def list(self, *, username=None):
        return []

    def get(self, job_id):
        if job_id != "safe-job":
            return None
        return {"job_id": job_id, "username": "admin", "status": "completed"}

    def artifact(self, job_id):
        item = self.get(job_id)
        if item is None:
            raise KeyError(job_id)
        return item, self.path


def client(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    store.create_user("admin2", "Admin Two", Role.ADMINISTRATOR, "Password123!", "1357")
    store.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "9999")
    app = FastAPI()
    attach_secure_routes(app, security=store, audit=AuditTrail(store), alarm_mirror=RemoteAlarmMirror(store), alarm_control=AlarmControl(), device_admin=DeviceAdmin(), report_jobs=ReportJobs(tmp_path / "safe.pdf"))
    web = TestClient(app)
    assert web.post("/auth/login", json={"username": "admin", "password": "Password123!"}).status_code == 200
    return web, store


def test_user_mutations_require_pin_and_invalidate_target_sessions(tmp_path):
    web, store = client(tmp_path)
    target_token = store.create_session("operator")
    rejected = web.patch("/api/v1/control/users/operator", json={"display_name": "Changed", "role": "Viewer", "pin": "0000"})
    assert rejected.status_code == 403
    changed = web.patch("/api/v1/control/users/operator", json={"display_name": "Changed", "role": "Viewer", "pin": "2468"})
    assert changed.status_code == 200
    assert changed.json()["display_name"] == "Changed"
    assert store.session_user(target_token) is None
    assert "password" not in changed.text.lower()
    assert "pin_hash" not in changed.text.lower()


def test_final_enabled_admin_and_self_lockout_are_rejected(tmp_path):
    web, _store = client(tmp_path)
    assert web.post("/api/v1/control/users/admin2/enabled", json={"enabled": False, "pin": "2468"}).status_code == 200
    assert web.post("/api/v1/control/users/admin/enabled", json={"enabled": False, "pin": "2468"}).status_code == 409
    assert web.request("DELETE", "/api/v1/control/users/admin", json={"pin": "2468"}).status_code == 409


def test_operator_can_edit_station_but_viewer_cannot(tmp_path):
    web, _store = client(tmp_path)
    assert web.post("/api/v1/control/stations/5201", json={"pin": "2468", "changes": {"description": "offline note"}}).status_code == 200
    web.post("/auth/logout")
    assert web.post("/auth/login", json={"username": "operator", "password": "Password123!"}).status_code == 200
    assert web.post("/api/v1/control/stations/5201", json={"pin": "9999", "changes": {"name": "Operator edit"}}).status_code == 200
    web.post("/auth/logout")
    # No synthetic viewer identity can satisfy the editor dependency.
    assert web.post("/api/v1/control/stations/5201", json={"pin": "9999", "changes": {"name": "No session"}}).status_code == 401


def test_report_artifact_requires_operator_session_and_uses_job_id_only(tmp_path):
    web, _store = client(tmp_path)
    web.post("/auth/logout")
    assert web.get("/api/v1/control/reports/safe-job/download").status_code == 401
    assert web.post("/auth/login", json={"username": "operator", "password": "Password123!"}).status_code == 200
    response = web.get("/api/v1/control/reports/safe-job/download")
    assert response.status_code == 403
    assert web.get("/api/v1/control/reports/../../security.db/download").status_code in {404, 409}


def test_report_owner_and_administrator_can_download_artifact(tmp_path):
    web, _store = client(tmp_path)
    owner = web.get("/api/v1/control/reports/safe-job/download")
    assert owner.status_code == 200
    assert owner.content.startswith(b"%PDF")
