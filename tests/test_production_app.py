from pathlib import Path

import pytest

from radmon.paths import ApplicationPaths
from radmon.production_app import run_production


class FakeLock:
    def __init__(self, events, acquired=True):
        self.events = events
        self.acquired = acquired

    def acquire(self):
        self.events.append("lock")
        return self.acquired

    def release(self):
        self.events.append("unlock")


class FakeCentral:
    def __init__(self, events):
        self.events = events
        self.services = object()
        self.archive_catalog = object()

    def start(self):
        self.events.append("central-start")

    def stop(self):
        self.events.append("central-stop")


def _paths(tmp_path: Path) -> ApplicationPaths:
    return ApplicationPaths(
        tmp_path,
        tmp_path / "app",
        tmp_path / "config",
        tmp_path / "runtime",
        tmp_path / "archives",
        tmp_path / "reports",
        tmp_path / "runtime" / "logs",
        tmp_path / "app" / "assets",
        tmp_path / "app" / "grafana",
    )


def test_supervisor_stops_central_when_desktop_exits(tmp_path):
    events = []
    central = FakeCentral(events)
    code = run_production(
        paths=_paths(tmp_path),
        central_factory=lambda *a, **k: central,
        desktop_runner=lambda *a, **k: events.append("desktop") or 0,
        lock_factory=lambda port: FakeLock(events),
        grafana_startup=lambda *a, **k: events.append("grafana"),
        listener_owner=lambda port: None,
    )
    assert code == 0
    assert events == ["lock", "central-start", "grafana", "desktop", "central-stop", "unlock"]


def test_supervisor_cleans_up_when_desktop_raises(tmp_path):
    events = []
    central = FakeCentral(events)

    def fail_desktop(*args, **kwargs):
        events.append("desktop")
        raise RuntimeError("ui failed")

    with pytest.raises(RuntimeError, match="ui failed"):
        run_production(
            paths=_paths(tmp_path),
            central_factory=lambda *a, **k: central,
            desktop_runner=fail_desktop,
            lock_factory=lambda port: FakeLock(events),
            grafana_startup=lambda *a, **k: events.append("grafana"),
            listener_owner=lambda port: None,
        )
    assert events == ["lock", "central-start", "grafana", "desktop", "central-stop", "unlock"]


def test_supervisor_refuses_duplicate_instance_before_starting_central(tmp_path):
    events = []
    central = FakeCentral(events)
    code = run_production(
        paths=_paths(tmp_path),
        central_factory=lambda *a, **k: central,
        desktop_runner=lambda *a, **k: 0,
        lock_factory=lambda port: FakeLock(events, acquired=False),
        grafana_startup=lambda *a, **k: None,
        listener_owner=lambda port: None,
    )
    assert code == 2
    assert events == ["lock"]


def test_supervisor_refuses_foreign_port_owner(tmp_path):
    from radmon.process_ownership import PortOwner

    events = []
    central = FakeCentral(events)
    with pytest.raises(RuntimeError, match="Port 8090 dipakai proses lain"):
        run_production(
            paths=_paths(tmp_path),
            central_factory=lambda *a, **k: central,
            desktop_runner=lambda *a, **k: 0,
            lock_factory=lambda port: FakeLock(events),
            grafana_startup=lambda *a, **k: None,
            listener_owner=lambda port: PortOwner(999, "foreign.exe"),
        )
    assert events == ["lock", "unlock"]
