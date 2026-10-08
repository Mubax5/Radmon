"""Standalone desktop admin client for the already-owned RadMon runtime."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from PySide6.QtWidgets import QApplication, QMessageBox

from .archive import ArchiveCatalog
from .config import Settings
from .desktop_app import run_admin_ui
from .logging_setup import configure_logging
from .paths import ApplicationPaths
from .secure_services import build_secure_services


def central_is_available(host: str = "127.0.0.1", port: int = 8090, timeout: float = 0.5) -> bool:
    try:
        with urlopen(f"http://{host}:{int(port)}/health", timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and payload.get("status") == "ok"
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def _ensure_central(paths: ApplicationPaths, *, timeout: float = 90.0) -> bool:
    if central_is_available():
        return True
    server_exe = paths.app_dir / "RadMon.exe"
    if not server_exe.is_file():
        return False
    try:
        subprocess.Popen(
            [str(server_exe), "--start"],
            cwd=str(paths.app_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                           | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
        )
    except OSError:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if central_is_available():
            return True
        time.sleep(0.5)
    return central_is_available()


def run_admin_client(paths: ApplicationPaths | None = None) -> int:
    """Attach the desktop to shared central data without starting server workers."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("RadMon Admin")
    paths = paths or ApplicationPaths.discover()
    for folder in (paths.config_dir, paths.runtime_dir, paths.archive_dir, paths.report_dir, paths.log_dir):
        folder.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(paths.env_file).for_application_paths(paths)
    if not central_is_available():
        answer = QMessageBox.question(
            None,
            "Start RadMon Central?",
            "RadMon Central is not running. Start the existing RadMon server now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return 2
    if not _ensure_central(paths):
        QMessageBox.critical(
            None,
            "RadMon Central tidak tersedia",
            "RadMon Admin tidak dapat menghubungi Central API. Pastikan RadMon.exe tersedia dan server dapat dimulai.",
        )
        return 2

    try:
        # These adapters use the central runtime's configured security database and
        # authoritative MariaDB. No service lifecycle or acquisition worker is started.
        services = build_secure_services(settings)
        archive_catalog = ArchiveCatalog(
            services.security,
            settings.archive_dir,
            timezone_name=settings.archive_timezone,
        )
        log_path = configure_logging(settings.log_dir)
    except Exception as exc:
        QMessageBox.critical(None, "RadMon Admin", str(exc))
        return 3
    return run_admin_ui(
        settings,
        services,
        archive_catalog,
        log_path,
        manage_grafana=False,
    )


def main() -> int:
    if "--smoke-test" in sys.argv[1:]:
        return 0 if central_is_available() else 1
    return run_admin_client()


if __name__ == "__main__":
    raise SystemExit(main())
