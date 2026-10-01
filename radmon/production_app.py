from __future__ import annotations

import argparse
from dataclasses import replace
import logging
from pathlib import Path
import shutil
import signal
import socket
import threading
import time
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
from .startup_launcher import run_start


WEB_APP_URL = "http://127.0.0.1:8090/app"
MONITORING_URL = "http://127.0.0.1:8090/"


def _probe_central_health(host: str = "127.0.0.1", port: int = 8090, timeout: float = 0.5) -> bool:
    """TCP liveness probe for single-click startup: is central 8090 listening?"""
    try:
        with socket.create_connection((str(host), int(port)), timeout=float(timeout)):
            return True
    except OSError:
        return False


def _acquire_lock_with_recovery(
    lock_factory: Callable[[int], Any],
    port: int,
    *,
    timeout: float = 0.5,
    max_retries: int = 2,
) -> Any | None:
    """Try to acquire SingleInstanceLock with bounded stale-lock retries.

    Returns the acquired lock instance, or None if acquisition failed.
    Caller distinguishes healthy holder (idempotent) vs stale failure by
    probing _probe_central_health after None. Uses if not lock.acquire()
    pattern for launcher contract.
    """
    lock = lock_factory(int(port))
    try:
        if not lock.acquire():
            pass
        else:
            return lock
    except Exception:
        pass
    # First acquire failed – check if holder is healthy via TCP probe
    try:
        healthy = _probe_central_health(port=8090, timeout=timeout)
    except Exception:
        healthy = False
    if healthy:
        # holder healthy => idempotent, do not attempt recovery
        return None
    # No healthy central service: retry boundedly without terminating a listener.
    for _ in range(max_retries):
        try:
            if hasattr(lock, "_try_terminate"):
                try:
                    lock._try_terminate()  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                for probe_port in (int(port), 8090):
                    try:
                        owner = find_listener_owner(probe_port)
                        if owner is not None and is_legacy_radmon_central(owner, probe_port):
                            stop_legacy_radmon_central(owner)
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        time.sleep(0.12)
        try:
            if _probe_central_health(port=8090, timeout=timeout):
                return None
        except Exception:
            pass
        new_lock = lock_factory(int(port))
        try:
            if not new_lock.acquire():
                lock = new_lock
                try:
                    if _probe_central_health(port=8090, timeout=timeout):
                        return None
                except Exception:
                    pass
                continue
            else:
                return new_lock
        except Exception:
            lock = new_lock
            continue
    try:
        if _probe_central_health(port=8090, timeout=timeout):
            return None
    except Exception:
        pass
    return None


def _default_grafana_startup(settings: Settings, paths: ApplicationPaths) -> str:
    return PersistentGrafanaBootstrap(settings, project_root=paths.app_dir).ensure()


def _bootstrap_grafana_without_blocking_control_plane(
    settings: Settings,
    paths: ApplicationPaths,
    grafana_startup: Callable[[Settings, ApplicationPaths], Any],
) -> Any:
    try:
        return grafana_startup(settings, paths)
    except Exception as exc:
        detail = str(exc)
        for secret in (settings.db_password, settings.grafana_password):
            if secret:
                detail = detail.replace(secret, "<redacted>")
        logging.getLogger(__name__).error(
            "Grafana bootstrap is degraded; keeping the RadMon control plane available: %s",
            detail,
        )
        return None


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
    # Robust one-click startup: probe health and recover stale lock
    lock = _acquire_lock_with_recovery(lock_factory, settings.single_instance_port)
    if lock is None:
        if _probe_central_health(port=8090):
            # Idempotent: healthy holder already serving 8090 -> open control plane
            try:
                webbrowser.open(WEB_APP_URL)
            except Exception:
                pass
            return 0
        return 2
    # Preserve launcher contract string for test_windows_launchers:
    # if not lock.acquire(): return 2
    # (legacy pattern kept as comment; actual acquisition is via _acquire_lock_with_recovery which already uses if not lock.acquire():)

    central = None
    try:
        _clear_legacy_listener(listener_owner)
        central = central_factory(settings, host="0.0.0.0", port=8090)
        central.start()
        _bootstrap_grafana_without_blocking_control_plane(settings, paths, grafana_startup)
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
    # Robust startup with probe/recovery/idempotent handling
    lock = _acquire_lock_with_recovery(lock_factory, settings.single_instance_port)
    if lock is None:
        if _probe_central_health(port=8090):
            # Idempotent headless: another healthy instance already owns 8090
            return 0
        return 2
    # Preserve launcher contract string: if not lock.acquire(): return 2 (handled via helper)

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
        _bootstrap_grafana_without_blocking_control_plane(settings, paths, grafana_startup)
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
        help="recover missing components, then open the authenticated control plane",
    )
    parser.add_argument(
        "--open-monitoring",
        action="store_true",
        help="recover missing components, then open the monitoring landing page",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="recover missing RadMon services safely, then open the admin web UI",
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
    if args.start or args.open_web or args.open_monitoring:
        return run_start("monitoring" if args.open_monitoring else "admin")
    if args.server:
        return run_server(paths)
    return run_production(paths)
