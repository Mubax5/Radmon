from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence, Any

from .central_service import CentralService, smoke_server_lifecycle
from .config import Settings
from .desktop_app import run_admin_ui
from .grafana_bootstrap import GrafanaBootstrap
from .logging_setup import configure_logging
from .paths import ApplicationPaths
from .process_ownership import (
    PortOwner,
    find_listener_owner,
    is_legacy_radmon_central,
    stop_legacy_radmon_central,
)
from .single_instance import SingleInstanceLock


def _default_grafana_startup(settings: Settings, paths: ApplicationPaths) -> str:
    return GrafanaBootstrap(settings, project_root=paths.app_dir).ensure()


def run_production(
    paths: ApplicationPaths | None = None,
    *,
    central_factory: Callable[..., Any] = CentralService,
    desktop_runner: Callable[..., int] = run_admin_ui,
    lock_factory: Callable[[int], Any] = SingleInstanceLock,
    grafana_startup: Callable[[Settings, ApplicationPaths], Any] = _default_grafana_startup,
    listener_owner: Callable[[int], PortOwner | None] = find_listener_owner,
) -> int:
    """Run the complete production central stack under one lifecycle owner."""
    paths = paths or ApplicationPaths.discover()
    for folder in (
        paths.config_dir,
        paths.runtime_dir,
        paths.archive_dir,
        paths.report_dir,
        paths.log_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    settings = Settings.from_env(paths.env_file).for_application_paths(paths)
    settings = replace(settings, lan_enabled=True)
    log_path = configure_logging(settings.log_dir)

    lock = lock_factory(settings.single_instance_port)
    if not lock.acquire():
        return 2

    central = None
    try:
        owner = listener_owner(8090)
        if owner is not None:
            if is_legacy_radmon_central(owner, 8090):
                stop_legacy_radmon_central(owner)
            else:
                raise RuntimeError(f"Port 8090 dipakai proses lain (PID {owner.pid})")

        central = central_factory(settings, host="0.0.0.0", port=8090)
        central.start()
        grafana_startup(settings, paths)
        return int(
            desktop_runner(
                settings,
                central.services,
                central.archive_catalog,
                log_path,
            )
        )
    finally:
        try:
            if central is not None:
                central.stop()
        finally:
            lock.release()


def _smoke_test(paths: ApplicationPaths) -> int:
    # Import and path checks must not touch production MariaDB or credentials.
    if not paths.app_dir.exists():
        raise RuntimeError(f"application directory tidak ditemukan: {paths.app_dir}")
    smoke_server_lifecycle()
    print("RadMon smoke test OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RadMon production central application")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="validate packaged imports and managed API lifecycle without production DB access",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = ApplicationPaths.discover()
    if args.smoke_test:
        return _smoke_test(paths)
    return run_production(paths)
