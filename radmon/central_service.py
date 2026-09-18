from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import threading
import time
import logging
from typing import Any, Callable

from fastapi import FastAPI
import uvicorn

from .archive import ArchiveCatalog, QuarterArchiveService
from .archive_store import CentralArchiveStore
from .central_api import create_central_app
from .config import Settings
from .hot_path import RealtimeCentralMariaDBRepository
from .lan_runtime import LanRuntime
from .recent_read_model import RollingRecentManager
from .repository import MariaDBRepository
from .secure_api import attach_secure_routes
from .secure_services import build_secure_services
from .web_api import attach_web_api_routes
from .web_events import WebEventBroker
from .web_host import attach_web_routes
from .web_reports import WebReportJobs
from .whatsapp import SeleniumWhatsAppSender, WhatsAppAlarmDispatcher


LOG = logging.getLogger(__name__)


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


class ManagedUvicornServer:
    """Own one Uvicorn listener and restart an unexpectedly terminated worker."""

    def __init__(self, app, host: str, port: int, *, server_factory: Callable[[Any, str, int], Any] | None = None) -> None:
        self.app = app
        self.host = host
        self.port = int(port)
        self._server_factory = server_factory or self._new_uvicorn_server
        self._server: Any | None = None
        self._thread: threading.Thread | None = None
        self._supervisor: threading.Thread | None = None
        self._lock = threading.RLock()
        self._desired_running = False
        self._stopped = threading.Event()
        self._worker_exited = threading.Event()
        self._status_lock = threading.Lock()
        self._state = "STOPPED"
        self._last_error: str | None = None
        self._failure_count = 0

    @staticmethod
    def _new_uvicorn_server(app, host: str, port: int):
        return uvicorn.Server(uvicorn.Config(app, host=host, port=port, reload=False, log_config=None))

    @staticmethod
    def _exception_detail(exc: BaseException) -> str:
        try:
            text = str(exc).replace("\n", " ").replace("\r", " ")
        except Exception:
            text = "unprintable exception"
        return f"{type(exc).__name__}: {text[:500]}"

    @property
    def status(self) -> dict[str, object]:
        running = self.running
        with self._status_lock:
            return {
                "state": self._state,
                "last_error": self._last_error,
                "failure_count": self._failure_count,
                "running": running,
            }

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive() and self._server and self._server.started)

    def _set_status(self, state: str, error: str | None = None, *, failed: bool = False) -> None:
        with self._status_lock:
            self._state = state
            self._last_error = error
            if failed:
                self._failure_count += 1

    def _run_worker(self, server) -> None:
        unexpected_error: str | None = None
        try:
            server.run()
        except BaseException as exc:
            unexpected_error = self._exception_detail(exc)
            LOG.exception("central API listener terminated with an exception")
        finally:
            with self._lock:
                desired = self._desired_running
            if desired:
                detail = unexpected_error or "Uvicorn listener exited unexpectedly"
                self._set_status("DEGRADED", detail, failed=True)
                LOG.error("central API listener unavailable on %s:%s: %s", self.host, self.port, detail)
                self._worker_exited.set()

    def _start_worker_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._worker_exited.clear()
        self._server = self._server_factory(self.app, self.host, self.port)
        self._thread = threading.Thread(
            target=self._run_worker, args=(self._server,), name="radmon-central-api", daemon=False,
        )
        self._thread.start()

    def _supervise(self) -> None:
        while not self._stopped.wait(0.1):
            if not self._worker_exited.is_set():
                continue
            with self._lock:
                if not self._desired_running:
                    return
                worker = self._thread
            if worker is not None:
                worker.join(timeout=0)
                if worker.is_alive():
                    continue
            with self._status_lock:
                delay = min(0.25 * (2 ** min(self._failure_count - 1, 5)), 8.0)
            LOG.warning("central API listener restart scheduled in %.2fs", delay)
            if self._stopped.wait(delay):
                return
            with self._lock:
                if not self._desired_running or (self._thread is not None and self._thread.is_alive()):
                    continue
                self._set_status("RESTARTING", self._last_error)
                self._start_worker_locked()

    def start(self, timeout: float = 30.0) -> None:
        with self._lock:
            if self._desired_running and self.running:
                return
            if self._desired_running:
                raise RuntimeError("central API sedang memulai ulang")
            self._desired_running = True
            self._stopped.clear()
            self._set_status("STARTING")
            self._start_worker_locked()
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if self.running:
                self._set_status("OK")
                with self._lock:
                    if self._supervisor is None or not self._supervisor.is_alive():
                        self._supervisor = threading.Thread(
                            target=self._supervise, name="radmon-central-api-supervisor", daemon=True,
                        )
                        self._supervisor.start()
                return
            with self._lock:
                worker = self._thread
            if worker is None or not worker.is_alive():
                break
            time.sleep(0.05)
        self.stop(timeout=1.0)
        raise RuntimeError(f"central API gagal start pada {self.host}:{self.port}")

    def stop(self, timeout: float = 15.0) -> None:
        with self._lock:
            self._desired_running = False
            self._stopped.set()
            thread = self._thread
            server = self._server
            supervisor = self._supervisor
            if server is not None:
                server.should_exit = True
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=max(0.1, timeout))
        if thread is None:
            self._set_status("STOPPED")
            return
        thread.join(timeout=max(0.1, timeout))
        if thread.is_alive():
            if server is not None:
                server.force_exit = True
            thread.join(timeout=2.0)
        if thread.is_alive():
            raise RuntimeError("central API gagal berhenti")
        with self._lock:
            self._thread = None
            self._server = None
            self._supervisor = None
        self._set_status("STOPPED")


class SuppressionExpiryScheduler:
    """Periodically expire suppressions independently of LAN polling."""

    def __init__(self, expire_due: Callable[[], int], *, interval: float = 30.0, stop_event=None) -> None:
        self.expire_due = expire_due
        self.interval = max(0.1, float(interval))
        self.stop_event = stop_event or threading.Event()
        self._thread: threading.Thread | None = None
        self._status_lock = threading.Lock()
        self._last_error: str | None = None
        self._failure_count = 0

    @property
    def status(self) -> dict[str, object]:
        with self._status_lock:
            return {
                "state": "DEGRADED" if self._last_error else "OK",
                "last_error": self._last_error,
                "failure_count": self._failure_count,
            }

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.expire_due()
            except Exception as exc:
                # Expiry is retried on the next interval; do not terminate the
                # central lifecycle because its durable end operation is idempotent.
                try:
                    detail = str(exc)
                except Exception:
                    detail = "unprintable exception"
                error = f"{type(exc).__name__}: {detail}"
                with self._status_lock:
                    self._last_error = error
                    self._failure_count += 1
                LOG.exception("suppression expiry scheduler failed; will retry")
            else:
                with self._status_lock:
                    self._last_error = None
            self.stop_event.wait(self.interval)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="radmon-suppression-expiry", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self.stop_event.set()
        thread.join(timeout=max(0.1, timeout))
        if thread.is_alive():
            raise RuntimeError("suppression expiry scheduler gagal berhenti")
        self._thread = None


@dataclass(slots=True)
class CentralRuntime:
    app: Any
    services: Any
    archive_catalog: ArchiveCatalog
    lan_runtime: LanRuntime | None


def build_central_runtime(settings: Settings) -> CentralRuntime:
    """Build the complete central stack without starting background workers."""
    schema_repository = MariaDBRepository(settings)
    # Historical relations are validated before any rolling migration. The migration
    # may only recreate recent/vrecent and reads at most the latest three hours from
    # measurement.
    schema_repository.require_base_schema()

    services = build_secure_services(settings)
    services.runtime_status_projector.ensure_schema()
    RollingRecentManager(settings).ensure_schema()
    schema_repository.require_schema()
    services.alarm_policy.restore_and_reconcile_current_state()
    # Expiry is wall-clock based, not dependent on the next detector reading.
    services.alarm_suppression.expire_due()

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

    repository = RealtimeCentralMariaDBRepository(settings)
    report_jobs = WebReportJobs(services.security, services.audit, MariaDBRepository(settings), settings)
    web_events = WebEventBroker(max_queue=32)
    app = create_central_app(repository, settings)
    app.state.radmon_lan_enabled = bool(settings.lan_enabled)
    app.state.radmon_lan_source_count = len(services.sources) if settings.lan_enabled else 0
    app.state.radmon_web_events = web_events
    attach_secure_routes(
        app,
        security=services.security,
        audit=services.audit,
        alarm_mirror=services.alarm_mirror,
        alarm_control=services.alarm_control,
        device_admin=services.device_admin,
        user_admin=services.user_admin,
        report_jobs=report_jobs,
        cookie_secure=_enabled("RADMON_WEB_COOKIE_SECURE"),
        archive_catalog=archive_catalog,
        archive_service=archive_service,
        source_health=services.source_health,
        alarm_policy=services.alarm_policy,
        alarm_suppression=services.alarm_suppression,
    )
    attach_web_api_routes(
        app,
        security=services.security,
        repository=repository,
        source_health=services.source_health,
        event_broker=web_events,
    )
    attach_web_routes(app, settings=settings)

    @app.on_event("shutdown")
    async def stop_report_jobs() -> None:
        report_jobs.shutdown()

    whatsapp = None
    if _enabled("RADMON_WHATSAPP_ENABLED"):
        whatsapp = WhatsAppAlarmDispatcher(services.alarm_policy, SeleniumWhatsAppSender.from_env())

    lan_runtime = None
    if settings.lan_enabled:
        lan_runtime = LanRuntime(
            settings,
            services,
            whatsapp_dispatcher=whatsapp,
            archive_service=archive_service,
            web_event_broker=web_events,
        )

    return CentralRuntime(app=app, services=services, archive_catalog=archive_catalog, lan_runtime=lan_runtime)


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
        expiry_scheduler_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.host = host
        self.port = int(port)
        self._runtime_factory = runtime_factory
        self._api_factory = api_factory
        self._runtime: CentralRuntime | Any | None = None
        self._api: Any | None = None
        self._expiry_scheduler_factory = expiry_scheduler_factory or (
            lambda suppression: SuppressionExpiryScheduler(suppression.expire_due)
        )
        self._expiry_scheduler: Any | None = None

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
        expiry_started = False
        try:
            suppression = getattr(runtime.services, "alarm_suppression", None)
            if suppression is not None:
                scheduler = self._expiry_scheduler_factory(suppression)
                self._expiry_scheduler = scheduler
                app_state = getattr(runtime.app, "state", None)
                if app_state is not None:
                    app_state.radmon_suppression_expiry_scheduler = scheduler
                scheduler.start()
                expiry_started = True
            if runtime.lan_runtime is not None:
                runtime.lan_runtime.start()
                lan_started = True
            api = self._api_factory(runtime.app, self.host, self.port)
            self._api = api
            app_state = getattr(runtime.app, "state", None)
            if app_state is not None:
                app_state.radmon_api_server = api
            api.start()
        except Exception:
            self._api = None
            if lan_started:
                runtime.lan_runtime.stop()
            if expiry_started and self._expiry_scheduler is not None:
                self._expiry_scheduler.stop()
            self._expiry_scheduler = None
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
                except Exception as exc:
                    error = exc
            if self._expiry_scheduler is not None:
                try:
                    self._expiry_scheduler.stop()
                except Exception as exc:
                    if error is None:
                        error = exc
            if api is not None:
                try:
                    api.stop()
                except Exception as exc:
                    if error is None:
                        error = exc
        finally:
            self._api = None
            self._expiry_scheduler = None
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
