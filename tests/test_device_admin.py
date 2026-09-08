import pytest

from radmon.audit import AuditTrail
from radmon.device_admin import DeviceAdminService
from radmon.security import Role, SecurityStore


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


def test_operator_cannot_edit_station(setup):
    security, repo, service = setup
    op = security.authenticate("op", "Password123!")
    with pytest.raises(Exception):
        service.update_station(op, "1357", 5201, {"name": "Nope"})


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
