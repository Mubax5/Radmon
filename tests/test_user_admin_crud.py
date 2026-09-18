from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore, UserIdentity


class DeviceAdmin:
    pass


class AlarmControl:
    pass


def make_client(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    store.create_user("admin2", "Admin Two", Role.ADMINISTRATOR, "Password123!", "1357")
    store.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "9999")
    audit = AuditTrail(store)
    app = FastAPI()
    attach_secure_routes(
        app,
        security=store,
        audit=audit,
        alarm_mirror=RemoteAlarmMirror(store),
        alarm_control=AlarmControl(),
        device_admin=DeviceAdmin(),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "admin", "password": "Password123!"}).status_code == 200
    return client, store, audit


def test_user_crud_requires_admin_and_current_admin_pin(tmp_path):
    client, _store, _audit = make_client(tmp_path)

    assert client.get("/api/v1/control/users").status_code == 200
    assert client.post("/api/v1/control/users", json={
        "pin": "0000", "username": "new", "display_name": "New", "role": "Viewer",
        "password": "Password123!", "user_pin": "1234",
    }).status_code == 403
    assert client.patch("/api/v1/control/users/operator", json={
        "pin": "2468", "display_name": " ", "role": "Viewer",
    }).status_code == 422

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "operator", "password": "Password123!"}).status_code == 200
    assert client.get("/api/v1/control/users").status_code == 403
    assert client.patch("/api/v1/control/users/admin", json={
        "pin": "9999", "display_name": "No", "role": "Administrator",
    }).status_code == 403


def test_user_mutations_revoke_target_sessions_and_sensitive_leases(tmp_path):
    client, store, _audit = make_client(tmp_path)

    operator_session = store.create_session("operator")
    assert client.patch("/api/v1/control/users/operator", json={
        "pin": "2468", "display_name": "Changed", "role": "Viewer",
    }).status_code == 200
    assert store.session_user(operator_session) is None

    admin2 = UserIdentity("admin2", "Admin Two", Role.ADMINISTRATOR)
    admin2_session = store.create_session("admin2")
    store.require_sensitive(admin2, "manage_users", "1357")
    assert store.sensitive_lease_active(admin2)
    assert client.patch("/api/v1/control/users/admin2", json={
        "pin": "2468", "display_name": "Admin Dua", "role": "Administrator",
    }).status_code == 200
    assert store.session_user(admin2_session) is None
    assert not store.sensitive_lease_active(admin2)

    for path, payload in (
        ("/api/v1/control/users/operator/enabled", {"pin": "2468", "enabled": False}),
        ("/api/v1/control/users/operator/password", {"pin": "2468", "password": "Changed123!"}),
        ("/api/v1/control/users/operator/pin", {"pin": "2468", "new_pin": "1111"}),
    ):
        token = store.create_session("operator") if path.endswith("enabled") is False else None
        if path.endswith("enabled"):
            # Re-enable first so the target has an authenticated session to revoke.
            assert client.post("/api/v1/control/users/operator/enabled", json={"pin": "2468", "enabled": True}).status_code == 200
            token = store.create_session("operator")
        assert client.post(path, json=payload).status_code == 200
        assert token is not None and store.session_user(token) is None
        if path.endswith("enabled"):
            assert store.get_user("operator")["enabled"] is False
            assert client.post("/api/v1/control/users/operator/enabled", json={"pin": "2468", "enabled": True}).status_code == 200


def test_final_admin_and_self_lockout_are_conflicts_and_delete_is_logical(tmp_path):
    client, store, _audit = make_client(tmp_path)

    assert client.patch("/api/v1/control/users/admin", json={
        "pin": "2468", "display_name": "Admin", "role": "Viewer",
    }).status_code == 409
    assert client.post("/api/v1/control/users/admin/enabled", json={"pin": "2468", "enabled": False}).status_code == 409
    assert client.request("DELETE", "/api/v1/control/users/admin", json={"pin": "2468"}).status_code == 409

    target_session = store.create_session("operator")
    response = client.request("DELETE", "/api/v1/control/users/operator", json={"pin": "2468"})
    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"
    assert store.get_user("operator")["enabled"] is False
    assert store.session_user(target_session) is None


def test_user_audit_and_responses_never_include_credentials(tmp_path):
    client, store, audit = make_client(tmp_path)
    new_password = "NotInAudit123!"
    new_pin = "7777"

    assert client.post("/api/v1/control/users/operator/password", json={
        "pin": "2468", "password": new_password,
    }).status_code == 200
    assert client.post("/api/v1/control/users/operator/pin", json={
        "pin": "2468", "new_pin": new_pin,
    }).status_code == 200
    combined = "\n".join(str(event) for event in audit.list_events())
    assert new_password not in combined
    assert new_pin not in combined
    assert "2468" not in combined
    assert all("password_hash" not in str(row) and "pin_hash" not in str(row) for row in store.list_users())


def test_user_management_ui_uses_native_dialog_forms_and_controls():
    source = ("web/src/pages/UsersPage.tsx")
    actions = ("web/src/Actions.tsx")
    from pathlib import Path

    users = Path(source).read_text(encoding="utf-8")
    create_form = Path(actions).read_text(encoding="utf-8")
    assert "<dialog ref={dialog}" in users
    assert "<form className=\"action-form\"" in users
    assert "<select className=\"native-select\"" in users
    assert "Nonaktifkan pengguna" in users
    assert "<input type=\"password\"" in create_form
