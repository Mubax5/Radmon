from __future__ import annotations

from datetime import datetime
from dataclasses import replace

from radmon.config import Settings
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.secure_services import build_secure_services
from radmon.security import SecurityStore


def test_station_write_through_is_disabled_when_lan_runtime_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("RADMON_LAN_SOURCES", "gd50@192.168.1.50")
    monkeypatch.setenv("RADMON_LAN_ENABLED", "0")
    monkeypatch.setenv("RADMON_SECURITY_DB", str(tmp_path / "security.db"))
    settings = replace(Settings(), runtime_dir=tmp_path, lan_enabled=False)

    services = build_secure_services(settings)
    assert services.sources
    assert services.device_admin.write_through is False


def test_station_write_through_is_enabled_only_for_lan_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("RADMON_LAN_SOURCES", "gd50@192.168.1.50")
    monkeypatch.setenv("RADMON_LAN_ENABLED", "1")
    monkeypatch.setenv("RADMON_SECURITY_DB", str(tmp_path / "security.db"))
    settings = replace(Settings(), runtime_dir=tmp_path, lan_enabled=True)

    services = build_secure_services(settings)
    assert services.device_admin.write_through is True


def test_reconcile_source_active_keys_clears_externally_handled_alarm(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    mirror = RemoteAlarmMirror(store)
    event = datetime(2026, 6, 1, 8, 0, 0)
    mirror.mirror(
        "gd50",
        [{
            "serid": 3000,
            "dtoa": event,
            "lvl": 2,
            "mvalue": 155.0,
            "thvalue": 150.0,
            "nhit": 1,
            "ack": 0,
            "i_flag": 0,
            "i_op": None,
            "pic": None,
            "note": None,
        }],
    )
    assert len(mirror.list_alarms(active_only=True)) == 1

    handled = mirror.reconcile_source_active_keys("gd50", set())

    assert handled == [(3000, event)]
    assert mirror.list_alarms(active_only=True) == []


def test_desktop_context_clear_revokes_sensitive_lease(tmp_path):
    from radmon import secure_context
    from radmon.security import Role

    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Admin", Role.ADMINISTRATOR, "Password123!", "2468")
    identity = store.authenticate("admin", "Password123!")
    store.require_sensitive(identity, "edit_station", "2468")
    assert store.sensitive_lease_active(identity)

    context = secure_context.SecurityContext(
        identity=identity,
        security=store,
        audit=None,
        alarm_mirror=None,
        alarm_control=None,
        device_admin=None,
        user_admin=None,
    )
    secure_context.set_context(context)
    secure_context.set_context(None)

    assert store.sensitive_lease_active(identity) is False
