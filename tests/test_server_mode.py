from pathlib import Path
import threading

from radmon.paths import ApplicationPaths
from radmon.production_app import run_server


class FakeLock:
    def __init__(self, port: int) -> None:
        self.port = port
        self.released = False

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


class FakeCentral:
    instances = []

    def __init__(self, settings, host: str, port: int) -> None:
        self.settings = settings
        self.host = host
        self.port = port
        self.started = False
        self.stopped = False
        FakeCentral.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def paths(tmp_path: Path) -> ApplicationPaths:
    return ApplicationPaths(
        install_root=tmp_path,
        app_dir=tmp_path / "app",
        config_dir=tmp_path / "config",
        runtime_dir=tmp_path / "runtime",
        archive_dir=tmp_path / "archives",
        report_dir=tmp_path / "reports",
        log_dir=tmp_path / "runtime" / "logs",
        assets_dir=tmp_path / "app" / "assets",
        grafana_dir=tmp_path / "app" / "grafana",
    )


def test_headless_server_owns_central_until_stop_event(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    grafana_calls = []
    locks = []

    def lock_factory(port: int):
        lock = FakeLock(port)
        locks.append(lock)
        return lock

    result = run_server(
        paths(tmp_path),
        central_factory=FakeCentral,
        lock_factory=lock_factory,
        grafana_startup=lambda settings, app_paths: grafana_calls.append((settings, app_paths)),
        listener_owner=lambda port: None,
        stop_event=event,
    )

    central = FakeCentral.instances[-1]
    assert result == 0
    assert central.host == "0.0.0.0" and central.port == 8090
    assert central.started is True and central.stopped is True
    assert len(grafana_calls) == 1
    assert locks[-1].released is True
