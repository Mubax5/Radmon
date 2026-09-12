from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import threading
import time
from typing import Any, Callable

from fastapi import FastAPI
import uvicorn

from .archive import ArchiveCatalog, QuarterArchiveService
from .archive_store import CentralArchiveStore
from .central_api import CentralMariaDBRepository, create_central_app
from .config import Settings
from .lan_runtime import LanRuntime
from .repository import MariaDBRepository
from .secure_api import attach_secure_routes
from .secure_services import build_secure_services
from .whatsapp import SeleniumWhatsAppSender, WhatsAppAlarmDispatcher


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


class ManagedUvicornServer:
    """Own one Uvicorn server and its worker thread explicitly."""

    def __init__(self, app, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=self.port,
                reload=False,
                log_config=None,
            )
        )
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server.started)

    def start(self, timeout: float = 30.0) -> None:
        if self.running:
            return
        self._server.should_exit = False
        self._server.force_exit = False
        self._thread = threading.Thread(
            target=self._server.run,
            name="radmon-central-api",
            daemon=False,
        )
        self._thread.start()
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if self._server.started:
                return
            if not self._thread.is_alive():
                break
            time.sleep(0.05)
        self.stop(timeout=1.0)
        raise RuntimeError(f"central API gagal start pada {self.host}:{self.port}")

    def stop(self, timeout: float = 15.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._server.should_exit = True
        thread.join(timeout=max(0.1, timeout))
        if thread.is_alive():
            self._server.force_exit = True
            thread.join(timeout=2.0)
        if thread.is_alive():
            raise RuntimeError("central API gagal berhenti")
        self._thread = None


@dataclass(slots=True)
class CentralRuntime:
    app: Any
    services: Any
    archive_catalog: ArchiveCatalog
    lan_runtime: LanRuntime | None


def build_central_runtime(settings: Settings) -> CentralRuntime:
    """Build the complete central stack without starting background workers."""
    MariaDBRepository(settings).require_schema()

    services = build_secure_services(settings)
    services.runtime_status_projector.ensure_schema()
    services.alarm_policy.restore_and_reconcile_current_state()

    archive_catalog = ArchiveCatalog(
        services.security,
        settings.archive_dir,
        timezone_name=settings.archive_timezone,
    )
    archive_catalog.reconcile()

    archive_service = None
    if settings.archive_enabled:
        archive_service = QuarterArchiveService(
            CentralArchiveStore(settings),
            archive_catalog,
            services.audit,
            settings.archive_dir,
            timezone_name=settings.archive_timezone,
        )

    app = create_central_app(CentralMariaDBRepository(settings), settings)
    app.state.radmon_lan_enabled = bool(settings.lan_enabled)
    app.state.radmon_lan_source_count = len(services.sources) if settings.lan_enabled else 0
    attach_secure_routes(
        app,
        security=services.security,
        audit=services.audit,
        alarm_mirror=services.alarm_mirror,
        alarm_control=services.alarm_control,
        device_admin=services.device_admin,
        cookie_secure=_enabled("RADMON_WEB_COOKIE_SECURE"),
        archive_catalog=archive_catalog,
        archive_service=archive_service,
        source_health=services.source_health,
        alarm_policy=services.alarm_policy,
        alarm_suppression=services.alarm_suppression,
    )

    whatsapp = None
    if _enabled("RADMON_WHATSAPP_ENABLED"):
        whatsapp = WhatsAppAlarmDispatcher(
            services.alarm_policy,
            SeleniumWhatsAppSender.from_env(),
        )

    lan_runtime = None
    if settings.lan_enabled:
        lan_runtime = LanRuntime(
            settings,
            services,
            whatsapp_dispatcher=whatsapp,
            archive_service=archive_service,
        )

    return CentralRuntime(
        app=app,
        services=services,
        archive_catalog=archive_catalog,
        lan_runtime=lan_runtime,
    )


class CentralService:
    """Own construction, startup, and shutdown of the central LAN/API stack."""

    def __init__(
        self,
        settings: Settings,
        host: str = "0.0.0.0",
        port: int = 8090,
        *,
        runtime_factory: Callable[[Settings], CentralRuntime] = build_central_runtime,
        api_factory: Callable[[Any, str, int], Any] = ManagedUvicornServer,
    ) -> None:
        self.settings = settings
        self.host = host
        self.port = int(port)
        self._runtime_factory = runtime_factory
        self._api_factory = api_factory
        self._runtime: CentralRuntime | Any | None = None
        self._api: Any | None = None

    @property
    def running(self) -> bool:
        return bool(self._api is not None and self._api.running)

    @property
    def services(self):
        if self._runtime is None:
            raise RuntimeError("central service belum dijalankan")
        return self._runtime.services

    @property
    def archive_catalog(self):
        if self._runtime is None:
            raise RuntimeError("central service belum dijalankan")
        return self._runtime.archive_catalog

    def start(self) -> None:
        if self.running:
            return
        runtime = self._runtime_factory(self.settings)
        self._runtime = runtime
        lan_started = False
        try:
            if runtime.lan_runtime is not None:
                runtime.lan_runtime.start()
                lan_started = True
            api = self._api_factory(runtime.app, self.host, self.port)
            self._api = api
            api.start()
        except Exception:
            self._api = None
            if lan_started:
                runtime.lan_runtime.stop()
            self._runtime = None
            raise

    def stop(self) -> None:
        runtime = self._runtime
        api = self._api
        if runtime is None and api is None:
            return
        error: Exception | None = None
        try:
            if runtime is not None and runtime.lan_runtime is not None:
                try:
                    runtime.lan_runtime.stop()
                except Exception as exc:  # preserve API cleanup even if LAN stop fails
                    error = exc
            if api is not None:
                try:
                    api.stop()
                except Exception as exc:
                    if error is None:
                        error = exc
        finally:
            self._api = None
            self._runtime = None
        if error is not None:
            raise error


def _free_local_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def smoke_server_lifecycle() -> None:
    """Exercise packaged server imports/start/stop without production DB access."""
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    server = ManagedUvicornServer(app, "127.0.0.1", _free_local_port())
    server.start(timeout=5.0)
    server.stop(timeout=5.0)
