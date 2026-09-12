from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import shutil
import signal
import threading
import webbrowser
from typing import Callable, Sequence, Any

from .central_service import CentralService, smoke_server_lifecycle
from .config import Settings
from .desktop_app import run_admin_ui
from .grafana_persistent import PersistentGrafanaBootstrap
from .logging_setup import configure_logging
from .paths import ApplicationPaths
from .process_ownership import (
    PortOwner,
    find_listener_owner,
    is_legacy_radmon_central,
    stop_legacy_radmon_central,
)
from .single_instance import SingleInstanceLock


WEB_APP_URL = "http://127.0.0.1:8090/app"
MONITORING_URL = "http://127.0.0.1:8090/"


def _default_grafana_startup(settings: Settings, paths: ApplicationPaths) -> str:
    return PersistentGrafanaBootstrap(settings, project_root=paths.install_root).ensure()


def _migrate_legacy_env(paths: ApplicationPaths) -> bool:
    """Copy a legacy install-root .env into external config exactly once."""
    legacy_env = paths.install_root / ".env"
    target_env = paths.env_file
    if legacy_env.resolve() == target_env.resolve():
        return False
    if target_env.exists() or not legacy_env.is_file():
        return False
    target_env.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_env, target_env)
    return True


def _prepare_settings(paths: ApplicationPaths) -> tuple[Settings, Path]:
    for folder in (
        paths.config_dir,
        paths.runtime_dir,
        paths.archive_dir,
        paths.report_dir,
        paths.log_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_env(paths)
    settings = Settings.from_env(paths.env_file).for_application_paths(paths)
    settings = replace(settings, lan_enabled=True)
    return settings, configure_logging(settings.log_dir)


def _clear_legacy_listener(listener_owner: Callable[[int], PortOwner | None]) -> None:
    owner = listener_owner(8090)
    if owner is None:
        return
    if is_legacy_radmon_central(owner, 8090):
        stop_legacy_radmon_central(owner)
        return
    raise RuntimeError(f"Port 8090 dipakai proses lain (PID {owner.pid})")


def run_production(
    paths: ApplicationPaths | None = None,
    *,
    central_factory: Callable[..., Any] = CentralService,
    desktop_runner: Callable[..., int] = run_admin_ui,
    lock_factory: Callable[[int], Any] = SingleInstanceLock,
    grafana_startup: Callable[[Settings, ApplicationPaths], Any] = _default_grafana_startup,
    listener_owner: Callable[[int], PortOwner | None] = find_listener_owner,
) -> int:
    """Run the local emergency desktop under the central lifecycle owner."""
    paths = paths or ApplicationPaths.discover()
    settings, log_path = _prepare_settings(paths)
    lock = lock_factory(settings.single_instance_port)
    if not lock.acquire():
        return 2

    central = None
    try:
        _clear_legacy_listener(listener_owner)
        central = central_factory(settings, host="0.0.0.0", port=8090)
        central.start()
        grafana_startup(settings, paths)
        return int(desktop_runner(settings, central.services, central.archive_catalog, log_path))
    finally:
        try:
            if central is not None:
                central.stop()
        finally:
            lock.release()


def run_server(
    paths: ApplicationPaths | None = None,
    *,
    central_factory: Callable[..., Any] = CentralService,
    lock_factory: Callable[[int], Any] = SingleInstanceLock,
    grafana_startup: Callable[[Settings, ApplicationPaths], Any] = _default_grafana_startup,
    listener_owner: Callable[[int], PortOwner | None] = find_listener_owner,
    stop_event: threading.Event | None = None,
) -> int:
    """Run RadMon headlessly for 24/7 Windows operation."""
    paths = paths or ApplicationPaths.discover()
    settings, _log_path = _prepare_settings(paths)
    lock = lock_factory(settings.single_instance_port)
    if not lock.acquire():
        return 2

    event = stop_event or threading.Event()
    central = None
    previous_handlers: dict[int, Any] = {}

    def request_stop(_signum=None, _frame=None) -> None:
        event.set()

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                try:
                    previous_handlers[int(signum)] = signal.getsignal(signum)
                    signal.signal(signum, request_stop)
                except (OSError, ValueError):
                    pass

        _clear_legacy_listener(listener_owner)
        central = central_factory(settings, host="0.0.0.0", port=8090)
        central.start()
        grafana_startup(settings, paths)
        while not event.wait(1.0):
            pass
        return 0
    finally:
        try:
            if central is not None:
                central.stop()
        finally:
            for signum, handler in previous_handlers.items():
                try:
                    signal.signal(signum, handler)
                except (OSError, ValueError):
                    pass
            lock.release()


def _smoke_test(paths: ApplicationPaths) -> int:
    if not paths.app_dir.exists():
        raise RuntimeError(f"application directory tidak ditemukan: {paths.app_dir}")
    smoke_server_lifecycle()
    print("RadMon smoke test OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RadMon production central application")
    parser.add_argument(
        "--server",
        action="store_true",
        help="run the headless 24/7 web platform without the PySide desktop",
    )
    parser.add_argument(
        "--open-web",
        action="store_true",
        help="open the authenticated RadMon control plane in the default browser",
    )
    parser.add_argument(
        "--open-monitoring",
        action="store_true",
        help="open the anonymous full-screen monitoring landing page",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="validate packaged imports and managed API lifecycle without production DB access",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = ApplicationPaths.discover()
    if args.smoke_test:
        return _smoke_test(paths)
    if args.open_web:
        webbrowser.open(WEB_APP_URL)
        return 0
    if args.open_monitoring:
        webbrowser.open(MONITORING_URL)
        return 0
    if args.server:
        return run_server(paths)
    return run_production(paths)
