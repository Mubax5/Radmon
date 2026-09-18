import pytest

from radmon.audit import AuditTrail
from radmon.device_admin import DeviceAdminService
from radmon.security import Role, SecurityError, SecurityStore


class FakeRepo:
    def __init__(self):
        self.rows = {
            5201: {
                "serid": 5201,
                "name": "IS-1",
                "location": "Gd.52",
                "description": "Old",
                "warnlevel": 23.0,
                "alarmlevel": 25.0,
                "maxidlemin": 30,
                "unit": "µSv/h",
            }
        }

    def get_device(self, serid):
        return dict(self.rows[int(serid)])

    def update_device(self, serid, changes):
        self.rows[int(serid)].update(changes)
        return self.get_device(serid)

    def create_device(self, serid, values):
        if int(serid) in self.rows:
            raise ValueError("exists")
        self.rows[int(serid)] = {"serid": int(serid), "name": "New", "location": "", "description": "", "warnlevel": 0, "alarmlevel": 0, "maxidlemin": 30, "unit": "uSv/h", **values}
        return self.get_device(serid)

    def delete_device(self, serid):
        self.rows.pop(int(serid))

    def migrate_serid(self, old_serid, new_serid):
        row = self.rows.pop(int(old_serid))
        row["serid"] = int(new_serid)
        self.rows[int(new_serid)] = row
        return dict(row)


@pytest.fixture
def setup(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    security.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    security.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "9876")
    repo = FakeRepo()
    service = DeviceAdminService(security, repo, AuditTrail(security))
    return security, repo, service


def test_admin_can_update_name_location_thresholds_with_pin(setup):
    security, repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    updated = service.update_station(
        admin,
        "2468",
        5201,
        {"name": "IS-1 Utama", "description": "Updated", "warnlevel": 20.0, "alarmlevel": 24.0},
    )
    assert updated["name"] == "IS-1 Utama"
    assert updated["description"] == "Updated"
    assert updated["warnlevel"] == 20.0
    assert updated["alarmlevel"] == 24.0


def test_operator_can_edit_station_with_pin(setup):
    security, repo, service = setup
    op = security.authenticate("op", "Password123!")
    assert service.update_station(op, "1357", 5201, {"name": "Updated by operator"})["name"] == "Updated by operator"


def test_station_edit_rejects_viewer_and_invalid_pin(setup):
    security, _repo, service = setup
    viewer = security.authenticate("viewer", "Password123!")
    admin = security.authenticate("admin", "Password123!")

    with pytest.raises(SecurityError):
        service.update_station(viewer, "9876", 5201, {"name": "Nope"})
    with pytest.raises(SecurityError, match="PIN"):
        service.update_station(admin, "0000", 5201, {"name": "Nope"})


def test_admin_can_migrate_tag_serid_with_pin(setup):
    security, repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    updated = service.migrate_serid(admin, "2468", 5201, 6201)
    assert updated["serid"] == 6201
    assert 5201 not in repo.rows
    assert 6201 in repo.rows


def test_threshold_validation_rejects_warn_above_alarm(setup):
    security, repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    with pytest.raises(ValueError):
        service.update_station(admin, "2468", 5201, {"warnlevel": 30, "alarmlevel": 25})


def test_lan_source_owned_station_cannot_be_deleted_or_migrated(setup):
    security, _repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    service.station_source = lambda serid: ("gd52", serid) if serid == 5201 else None
    with pytest.raises(ValueError, match="milik sumber LAN"):
        service.update_station(admin, "2468", 5201, {"name": "Duplicate"})
    with pytest.raises(ValueError, match="milik sumber LAN"):
        service.delete_station(admin, "2468", 5201)
    with pytest.raises(ValueError, match="milik sumber LAN"):
        service.migrate_serid(admin, "2468", 5201, 6201)
    with pytest.raises(ValueError, match="milik sumber LAN"):
        service.create_station(admin, "2468", 5201, {"name": "Duplicate", "location": "Gd.52", "warnlevel": 0, "alarmlevel": 0, "maxidlemin": 30})


def test_central_managed_station_remains_editable_when_lan_source_exists(setup):
    security, repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    service.station_source = lambda serid: ("gd52", serid) if serid == 9999 else None

    updated = service.update_station(admin, "2468", 5201, {"description": "central offline context"})

    assert updated["description"] == "central offline context"
    assert repo.rows[5201]["description"] == "central offline context"


def test_source_owned_station_cannot_be_deleted_when_write_through_is_unavailable(setup):
    security, _repo, service = setup
    admin = security.authenticate("admin", "Password123!")
    service.station_source = lambda serid: ("gd52", serid) if serid == 5201 else None

    with pytest.raises(ValueError, match="milik sumber LAN"):
        service.delete_station(admin, "2468", 5201)


def test_station_update_is_audited_without_recording_pin(setup):
    security, _repo, service = setup
    admin = security.authenticate("admin", "Password123!")

    service.update_station(admin, "2468", 5201, {"description": "updated context"})

    event = service.audit.list_events(limit=1)[0]
    assert event["action"] == "DEVICE_UPDATE"
    assert event["username"] == "admin"
    assert "updated context" in event["after_json"]
    assert "2468" not in event["after_json"]
