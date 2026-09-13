from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore


class FakeAlarmControl:
    def __init__(self, mirror):
        self.mirror = mirror
        self.calls = []

    def ack(self, identity, pin, source_id, serid, event_time, *, action, pic, note):
        self.calls.append((identity.username, pin, source_id, serid, event_time, action, pic, note))
        return {
            "source_id": source_id,
            "serid": serid,
            "event_time": event_time,
            "level": "ALARM",
            "acknowledged_at": datetime(2026, 9, 8, 14, 1, 0),
            "pic": pic,
            "action": action,
            "note": note,
        }


class FakeDeviceAdmin:
    def update_station(self, identity, pin, serid, changes):
        return {"serid": serid, **changes}


def make_client(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    security.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    security.create_user("view", "Viewer", Role.VIEWER, "Password123!", "9999")
    mirror = RemoteAlarmMirror(security)
    mirror.mirror("gd52", [{
        "serid": 5201,
        "dtoa": datetime(2026, 9, 8, 14, 0, 0),
        "lvl": 2,
        "mvalue": 26.1,
        "thvalue": 25.0,
        "nhit": 2,
        "i_op": None,
        "pic": None,
        "note": None,
    }])
    control = FakeAlarmControl(mirror)
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=AuditTrail(security),
        alarm_mirror=mirror,
        alarm_control=control,
        device_admin=FakeDeviceAdmin(),
        cookie_secure=False,
    )
    return TestClient(app), security, control


def login(client, username, password="Password123!"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response


def test_anonymous_control_routes_are_rejected(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/v1/control/alarms").status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_login_uses_httponly_session_cookie_and_logout_revokes_it(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = login(client, "op")
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/auth/me").json()["role"] == "Operator"
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_operator_can_ack_via_pin_gated_endpoint(tmp_path):
    client, _, control = make_client(tmp_path)
    login(client, "op")
    response = client.post(
        "/api/v1/control/alarms/gd52/5201/ack",
        json={
            "event_time": "2026-09-08T14:00:00",
            "action": "Confirm to Location",
            "pic": "Budi",
            "note": "checked",
            "pin": "1357",
        },
    )
    assert response.status_code == 200
    assert control.calls[0][0] == "op"
    assert control.calls[0][1] == "1357"


def test_viewer_cannot_use_mutating_control_endpoint(tmp_path):
    client, _, _ = make_client(tmp_path)
    login(client, "view")
    response = client.post(
        "/api/v1/control/stations/5201",
        json={"pin": "9999", "changes": {"name": "Nope"}},
    )
    assert response.status_code == 403


def test_admin_can_list_users_without_exposing_secret_hashes(tmp_path):
    client, _, _ = make_client(tmp_path)
    login(client, "admin")
    response = client.get("/api/v1/control/users")
    assert response.status_code == 200
    rows = response.json()
    assert {row["username"] for row in rows} == {"admin", "op", "view"}
    for row in rows:
        assert "password_hash" not in row
        assert "pin_hash" not in row
        assert "password" not in row
        assert "pin" not in row
