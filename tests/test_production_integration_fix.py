from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from radmon.audit import AuditTrail
from radmon.device_admin import DeviceAdminService
from radmon.lan import LanSource, RemoteMariaDBSource
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.security import Role, SecurityError, SecurityStore


def test_sensitive_pin_is_reused_for_ten_minutes_then_expires(tmp_path):
    clock = [datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)]
    store = SecurityStore(tmp_path / "security.db", now=lambda: clock[0])
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")

    store.require_sensitive(identity, "ack_alarm", "1357")
    assert store.sensitive_lease_active(identity) is True

    clock[0] += timedelta(minutes=9, seconds=59)
    store.require_sensitive(identity, "ack_alarm", "")

    clock[0] += timedelta(seconds=2)
    assert store.sensitive_lease_active(identity) is False
    with pytest.raises(SecurityError, match="PIN"):
        store.require_sensitive(identity, "ack_alarm", "")


def test_sensitive_lease_clear_requires_pin_again(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    identity = store.authenticate("admin", "Password123!")
    store.require_sensitive(identity, "edit_station", "2468")
    store.clear_sensitive_lease("admin")
    assert store.sensitive_lease_active(identity) is False
    with pytest.raises(SecurityError, match="PIN"):
        store.require_sensitive(identity, "edit_station", "")


def test_station_source_mapping_resolves_authoritative_remote_identity(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    assert store.resolve_station("gd52", 5201) == 5201
    assert store.station_source(5201) == ("gd52", 5201)


def test_station_source_mapping_rejects_ambiguous_central_identity(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.resolve_station("gd52", 5201)
    store.resolve_station("gd38", 5201)
    with pytest.raises(RuntimeError, match="ambiguous"):
        store.station_source(5201)


class _CentralDeviceRepo:
    def __init__(self, calls):
        self.calls = calls
        self.row = {
            "serid": 5201,
            "name": "IS-1",
            "location": "Gd.52",
            "description": "old",
            "warnlevel": 23.0,
            "alarmlevel": 25.0,
            "maxidlemin": 30,
            "unit": "µSv/h",
            "audiopath": "",
            "hwaddress": "gd52",
            "hwtype": "remote",
        }

    def get_device(self, serid):
        assert int(serid) == 5201
        return dict(self.row)

    def update_device(self, serid, changes):
        self.calls.append("central")
        self.row.update(changes)
        return dict(self.row)


class _RemoteDeviceRepo:
    def __init__(self, calls, *, fail=False):
        self.calls = calls
        self.fail = fail
        self.row = {
            "serid": 5201,
            "name": "IS-1",
            "location": "Gd.52",
            "description": "old",
            "warnlevel": 23.0,
            "alarmlevel": 25.0,
            "maxidlemin": 30,
            "unit": "µSv/h",
            "audiopath": "",
        }

    def update_device(self, serid, changes):
        self.calls.append("remote")
        if self.fail:
            raise RuntimeError("source write failed")
        self.row.update(changes)
        return dict(self.row)


def _lan_device_service(tmp_path, calls, *, fail=False):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    store.resolve_station("gd52", 5201)
    central = _CentralDeviceRepo(calls)
    remote = _RemoteDeviceRepo(calls, fail=fail)
    service = DeviceAdminService(
        store,
        central,
        AuditTrail(store),
        station_source=store.station_source,
        remote_factory=lambda source_id: remote,
        write_through=True,
    )
    return store, central, remote, service


def test_lan_station_edit_writes_source_before_central(tmp_path):
    calls = []
    store, central, remote, service = _lan_device_service(tmp_path, calls)
    identity = store.authenticate("admin", "Password123!")

    updated = service.update_station(
        identity,
        "2468",
        5201,
        {"warnlevel": 20.0, "alarmlevel": 24.0, "name": "IS-1 Utama"},
    )

    assert calls == ["remote", "central"]
    assert remote.row["warnlevel"] == 20.0
    assert central.row["warnlevel"] == 20.0
    assert updated["alarmlevel"] == 24.0


def test_lan_station_edit_does_not_mutate_central_when_source_write_fails(tmp_path):
    calls = []
    store, central, _remote, service = _lan_device_service(tmp_path, calls, fail=True)
    identity = store.authenticate("admin", "Password123!")

    with pytest.raises(RuntimeError, match="source write failed"):
        service.update_station(identity, "2468", 5201, {"warnlevel": 20.0, "alarmlevel": 24.0})

    assert calls == ["remote"]
    assert central.row["warnlevel"] == 23.0


def test_lan_station_edit_rejects_hardware_identity_fields(tmp_path):
    calls = []
    store, _central, _remote, service = _lan_device_service(tmp_path, calls)
    identity = store.authenticate("admin", "Password123!")
    with pytest.raises(ValueError, match="LAN"):
        service.update_station(identity, "2468", 5201, {"hwaddress": "changed"})


class _AlarmRemote:
    def __init__(self):
        self.respond_calls = []

    def respond_alarm(self, serid, dtoa, *, action, pic, note, at):
        self.respond_calls.append((serid, dtoa, action, pic, note, at))
        return True

    def ack_legacy(self, *args, **kwargs):
        raise AssertionError("legacy ack path must not be used")


def _alarm_row(*, i_flag=0, i_op=None):
    return {
        "serid": 5201,
        "dtoa": datetime(2026, 9, 10, 4, 30, 0),
        "lvl": 2,
        "mvalue": 26.1,
        "thvalue": 25.0,
        "nhit": 3,
        "ack": 0,
        "i_flag": i_flag,
        "i_op": i_op,
        "pic": None,
        "note": None,
    }


def test_alarm_active_only_follows_i_flag_even_without_i_op(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    mirror = RemoteAlarmMirror(store)
    row = _alarm_row(i_flag=0)
    mirror.mirror("gd52", [row])
    assert len(mirror.list_alarms(active_only=True)) == 1

    handled = dict(row, i_flag=1)
    mirror.mirror("gd52", [handled])
    assert mirror.list_alarms(active_only=True) == []


def test_alarm_response_is_one_step_and_uses_source_flag_path(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")
    mirror = RemoteAlarmMirror(store)
    mirror.mirror("gd52", [_alarm_row()])
    remote = _AlarmRemote()
    service = AlarmControlService(
        store,
        mirror,
        AuditTrail(store),
        remote_factory=lambda source_id: remote,
    )

    result = service.ack(
        identity,
        "1357",
        "gd52",
        5201,
        datetime(2026, 9, 10, 4, 30, 0),
        action="Confirm to Location",
        pic="Budi",
        note="Kondisi diperiksa",
    )

    assert len(remote.respond_calls) == 1
    assert result["is_active"] is False
    assert result["action"] == "Confirm to Location"


def test_remote_alarm_response_sql_sets_i_flag_without_touching_ack():
    class Cursor:
        rowcount = 1

        def __init__(self):
            self.sql = ""
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self.sql = sql
            self.params = params

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            pass

    connection = Connection()
    source = LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    remote = RemoteMariaDBSource(source, connection_factory=lambda: connection)
    assert hasattr(remote, "respond_alarm")
    ok = remote.respond_alarm(
        5201,
        datetime(2026, 9, 10, 4, 30, 0),
        action="Confirm to Location",
        pic="Budi",
        note="Kondisi diperiksa",
        at=datetime(2026, 9, 10, 4, 31, 0),
    )
    assert ok is True
    normalized = " ".join(connection.cursor_obj.sql.split()).lower()
    assert "i_flag = 1" in normalized
    assert "ack =" not in normalized
    assert connection.committed is True


def test_desktop_tree_has_source_grouping_helper_and_manuals_use_html():
    from radmon.admin import main_window

    grouping = getattr(main_window, "group_stations_by_source", None)
    assert callable(grouping)
    assert main_window.INSTALLATION_MANUAL_PATH == "docs/manual/installation.html"
    assert main_window.USER_MANUAL_PATH == "docs/manual/user-manual.html"
    assert Path(main_window.INSTALLATION_MANUAL_PATH).is_file()
    assert Path(main_window.USER_MANUAL_PATH).is_file()


def test_grouping_uses_source_mapping_not_serid_ranges():
    from radmon.admin import main_window

    station = SimpleNamespace(serid=9999, room="Detector X", location="Gd.X")
    groups = main_window.group_stations_by_source(
        [station],
        {9999: "gd50"},
        {"gd50": SimpleNamespace(source_id="gd50", host="192.168.1.50")},
        {"gd50": "CONNECTED"},
    )
    assert len(groups) == 1
    assert groups[0]["source_id"] == "gd50"
    assert groups[0]["host"] == "192.168.1.50"
    assert groups[0]["stations"] == [station]


def test_grafana_live_status_uses_database_threshold_columns_not_catalog_literals():
    from radmon.grafana_tv import build_dashboard_payloads

    operations = build_dashboard_payloads()[2]
    table = next(panel for panel in operations["panels"] if panel.get("description") == "operational-condition")
    sql = table["targets"][0]["rawSql"]
    assert "warnlevel" in sql
    assert "alarmlevel" in sql
    assert "FROM vrecent" in sql


def test_live_collector_inserts_current_vrecent_sample_into_measurement():
    import inspect
    from radmon.lan import MariaCentralStore

    source = inspect.getsource(MariaCentralStore.upsert_live_rows)
    assert "INSERT IGNORE INTO measurement" in source


def test_offline_status_is_not_sticky_after_new_measurement():
    from radmon.status import MonitorStatus, classify_status

    now = datetime(2026, 9, 10, 12, 0, 0)
    stale = classify_status(1.0, now - timedelta(minutes=31), now, 8.0, 10.0, 30)
    current = classify_status(1.0, now - timedelta(seconds=2), now, 8.0, 10.0, 30)
    assert stale is MonitorStatus.OFFLINE
    assert current is MonitorStatus.NORMAL
