from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.audit import AuditTrail
from radmon.device_admin import DeviceAdminService
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore


class StationRepository:
    def __init__(self):
        self.rows = {
            5201: {
                "serid": 5201,
                "name": "LAN station",
                "location": "Gd.52",
                "description": "Source owned",
                "warnlevel": 20.0,
                "alarmlevel": 25.0,
                "maxidlemin": 30,
                "unit": "uSv/h",
            },
            7001: {
                "serid": 7001,
                "name": "Central station",
                "location": "Central",
                "description": "Central owned",
                "warnlevel": 10.0,
                "alarmlevel": 15.0,
                "maxidlemin": 30,
                "unit": "uSv/h",
            },
        }
        self.history = {7001}

    def get_device(self, serid):
        row = self.rows.get(int(serid))
        return dict(row) if row else None

    def update_device(self, serid, changes):
        self.rows[int(serid)].update(changes)
        return self.get_device(serid)

    def create_device(self, serid, values):
        serid = int(serid)
        if serid in self.rows:
            raise ValueError("Tag/SERID sudah digunakan")
        self.rows[serid] = {"serid": serid, **values}
        return self.get_device(serid)

    def delete_device(self, serid):
        serid = int(serid)
        if serid in self.history:
            raise ValueError("stasiun yang memiliki measurement atau riwayat tidak dapat dihapus")
        self.rows.pop(serid)


class AlarmControl:
    pass


def station_client(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    security.create_user("operator", "Operator", Role.OPERATOR, "Password123!", "1357")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "9876")
    security.resolve_station("gd52", 5201)
    repository = StationRepository()
    audit = AuditTrail(security)
    app = FastAPI()
    attach_secure_routes(
        app,
        security=security,
        audit=audit,
        alarm_mirror=RemoteAlarmMirror(security),
        alarm_control=AlarmControl(),
        device_admin=DeviceAdminService(security, repository, audit, station_source=security.station_source),
    )
    return TestClient(app), repository, audit


def login(client, username):
    return client.post("/auth/login", json={"username": username, "password": "Password123!"})


def test_station_api_requires_editor_role_and_valid_pin(tmp_path):
    client, repository, audit = station_client(tmp_path)
    assert login(client, "viewer").status_code == 200
    assert client.post("/api/v1/control/stations/7001", json={"pin": "9876", "changes": {"name": "No"}}).status_code == 403

    client.post("/auth/logout")
    assert login(client, "operator").status_code == 200
    assert client.post("/api/v1/control/stations/7001", json={"pin": "0000", "changes": {"name": "No"}}).status_code == 400
    changed = client.post("/api/v1/control/stations/7001", json={"pin": "1357", "changes": {"name": "Edited", "warnlevel": 9.0, "alarmlevel": 14.0, "maxidlemin": 20}})

    assert changed.status_code == 200
    assert repository.rows[7001]["name"] == "Edited"
    event = audit.list_events(limit=1)[0]
    assert event["action"] == "DEVICE_UPDATE"
    assert event["username"] == "operator"
    assert "1357" not in (event["after_json"] or "")


def test_station_api_rejects_source_owned_mutations_and_preserves_history(tmp_path):
    client, repository, _audit = station_client(tmp_path)
    assert login(client, "admin").status_code == 200

    update = client.post("/api/v1/control/stations/5201", json={"pin": "2468", "changes": {"description": "override"}})
    create = client.post("/api/v1/control/stations", json={"pin": "2468", "serid": 5201, "values": {"name": "Duplicate", "location": "Gd.52", "warnlevel": 1, "alarmlevel": 2, "maxidlemin": 30}})
    delete_source = client.request("DELETE", "/api/v1/control/stations/5201", json={"pin": "2468"})
    delete_with_history = client.request("DELETE", "/api/v1/control/stations/7001", json={"pin": "2468"})

    assert update.status_code == create.status_code == delete_source.status_code == 400
    assert "sumber LAN" in update.json()["detail"]
    assert repository.rows[5201]["description"] == "Source owned"
    assert delete_with_history.status_code == 400
    assert 7001 in repository.rows
    assert 7001 in repository.history


def test_station_api_allows_only_safe_central_fields_and_audits_create_delete(tmp_path):
    client, repository, audit = station_client(tmp_path)
    assert login(client, "admin").status_code == 200

    forbidden = client.post("/api/v1/control/stations/7001", json={"pin": "2468", "changes": {"hwaddress": "changed"}})
    created = client.post("/api/v1/control/stations", json={"pin": "2468", "serid": 7002, "values": {"name": "New", "location": "Central", "description": "Created", "warnlevel": 1, "alarmlevel": 2, "maxidlemin": 30}})
    deleted = client.request("DELETE", "/api/v1/control/stations/7002", json={"pin": "2468"})

    assert forbidden.status_code == 422
    assert created.status_code == 200
    assert deleted.status_code == 200
    assert 7002 not in repository.rows
    assert [event["action"] for event in audit.list_events(limit=2)] == ["DEVICE_DELETE", "DEVICE_CREATE"]
