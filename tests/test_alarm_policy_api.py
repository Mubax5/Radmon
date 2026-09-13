from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.alarm_suppression import AlarmSuppressionService
from radmon.audit import AuditTrail
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore


class Mirror:
    def list_alarms(self, limit=500):
        return [{"source_id": "legacy", "serid": 1}]


class DeviceAdmin:
    def update_station(self, *args, **kwargs):
        return {}


class AlarmControl:
    def __init__(self, policy):
        self.policy = policy
    def ack(self, *args, **kwargs):
        return {"status": "legacy-ok"}
    def respond_policy_event(self, identity, pin, event_id, *, action, pic, reason):
        self.policy.store.security.require_sensitive(identity, "ack_alarm", pin)
        event = self.policy.mark_event_responded(event_id, datetime.now(timezone.utc), pic, action, reason)
        return {"event_id": event.event_id, "status": event.status}


def fixture(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "9999")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    control = AlarmControl(policy)
    suppression = AlarmSuppressionService(security, store, policy, audit, alarm_control=control)
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=audit,
        alarm_mirror=Mirror(),
        alarm_control=control,
        device_admin=DeviceAdmin(),
        alarm_policy=policy,
        alarm_suppression=suppression,
    )
    return TestClient(app), policy


def login(client, username):
    response = client.post("/auth/login", json={"username": username, "password": "Password123!"})
    assert response.status_code == 200


def test_unauthenticated_policy_controls_return_401(tmp_path):
    client, _ = fixture(tmp_path)
    assert client.get("/api/v1/control/alarm-events").status_code == 401
    assert client.get("/api/v1/control/suppressions").status_code == 401


def test_viewer_cannot_read_operator_alarm_workflow(tmp_path):
    client, _ = fixture(tmp_path)
    login(client, "viewer")
    assert client.get("/api/v1/control/alarm-events").status_code == 403
    assert client.get("/api/v1/control/alarm-policy/5201").status_code == 403
    assert client.get("/api/v1/control/suppressions").status_code == 403


def test_viewer_cannot_start_suppression(tmp_path):
    client, _ = fixture(tmp_path)
    login(client, "viewer")
    response = client.post("/api/v1/control/suppressions/5201", json={
        "pin": "9999", "duration_seconds": 900, "pic": "Viewer",
        "reason": "Calibration", "auto_resume_on_normal": True,
    })
    assert response.status_code == 403


def test_operator_can_start_list_and_query_suppression(tmp_path):
    client, policy = fixture(tmp_path)
    login(client, "operator")
    response = client.post("/api/v1/control/suppressions/5201", json={
        "pin": "1357", "duration_seconds": 900, "pic": "Budi",
        "reason": "Calibration", "auto_resume_on_normal": True,
    })
    assert response.status_code == 200
    listed = client.get("/api/v1/control/suppressions")
    assert listed.status_code == 200
    assert listed.json()[0]["serid"] == 5201
    status = client.get("/api/v1/control/alarm-policy/5201")
    assert status.status_code == 200
    assert status.json()["suppressed"] is True


def test_operator_can_respond_policy_event_and_legacy_route_stays_available(tmp_path):
    client, policy = fixture(tmp_path)
    snap = policy.evaluate_live({
        "serid": 5201,
        "dtom": datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        "doserate": 170.0,
        "warnlevel": 100.0,
        "alarmlevel": 150.0,
    })
    login(client, "operator")
    response = client.post(
        f"/api/v1/control/alarm-events/{snap['active_event_id']}/response",
        json={"pin": "1357", "action": "Confirm", "pic": "Budi", "reason": "checked"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESPONDED"
    assert client.get("/api/v1/control/alarms").status_code == 200


def test_suppression_payload_validation_and_overlap_conflict(tmp_path):
    client, _ = fixture(tmp_path)
    login(client, "operator")
    invalid = client.post("/api/v1/control/suppressions/5201", json={
        "pin": "1357", "duration_seconds": 59, "pic": "Budi", "reason": "x",
    })
    assert invalid.status_code == 422
    payload = {
        "pin": "1357", "duration_seconds": 300, "pic": "Budi",
        "reason": "Calibration", "auto_resume_on_normal": True,
    }
    assert client.post("/api/v1/control/suppressions/5201", json=payload).status_code == 200
    assert client.post("/api/v1/control/suppressions/5201", json=payload).status_code == 409
