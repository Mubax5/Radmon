# RadMon Production Release Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the developer-style Windows startup with one production `RadMon.exe`, consolidate every active runtime monkey patch into normal source modules, remove obsolete launchers/code/assets/history, and produce a verified Windows x64 PyInstaller `onedir` release whose shutdown releases every RadMon-owned service including port 8090.

**Architecture:** `radmon.production_app` becomes the single production supervisor. It resolves install/persistent paths, acquires single-instance ownership, safely recovers only positively identified legacy central processes, starts an in-process managed FastAPI/Uvicorn central service plus LAN runtime, provisions/reuses external Grafana, launches the existing PySide6 Admin UI, and shuts the complete RadMon-owned stack down when the GUI exits. Existing `*_revision.py` behavior is folded into its owning modules one group at a time, proven by targeted regression tests, then deleted before the final build.

**Tech Stack:** Python 3.12, PySide6, FastAPI/Uvicorn, MariaDB Connector/Python, SQLite sidecar state, Selenium, ReportLab, pyqtgraph, Grafana external integration, PyInstaller `onedir`, pytest, GitHub Actions Linux/Windows runners.

**Spec:** `docs/superpowers/specs/2026-09-12-radmon-production-release-cleanup-design.md`

## Global Constraints

- Production target is Windows x64 central PC `192.168.1.2`.
- Production operator launches only `RadMon.exe`; `.bat`, Python, `.venv`, `pip`, `pytest`, `main.py`, and `central_server.py` are not part of the final production SOP.
- Grafana remains external. Preserve supported healthy-existing, native-installed, and Docker fallback/provisioning behavior still used by the final bootstrap.
- Do not add source MariaDB DDL/migrations. Legacy detector/source database schemas remain untouched.
- Preserve configured production `source_id` values exactly; checkpoint/policy identity depends on them.
- Persistent central state survives application replacement: production `config/.env`, `runtime/`, `archives/`, and `reports/` stay outside replaceable `app/`.
- Preserve Alarm Policy, response/ACK, suppression, source write-through retry, archive, reports, source health, API, Grafana status projection, and notification behavior unless the approved spec explicitly changes lifecycle/packaging behavior.
- Suppression must not hide the measured dose value or rewrite historical source alarm evidence.
- RadMon may stop only a resource it owns or a process positively identified as a stale legacy RadMon central process. Never kill a foreign process solely because port 8090 is occupied.
- PyInstaller format is `onedir`, not `onefile`.
- New behavior and bug fixes follow TDD: failing test, verify RED, minimal implementation, verify GREEN, then refactor.
- Historical dated engineering design/implementation-plan documents are deleted before final merge. This working spec and plan are also deleted in the final cleanup commit after verification.

---

## Locked File Map

**Create**

- `radmon/paths.py` — source/frozen install, config, runtime, archive, report, log, asset, and Grafana paths.
- `radmon/central_service.py` — central runtime construction and managed Uvicorn lifecycle.
- `radmon/process_ownership.py` — conservative Windows listener/process inspection and legacy-central recovery.
- `radmon/desktop_app.py` — LAN Admin login/bootstrap/window flow without central or single-instance ownership.
- `radmon/production_app.py` — top-level production lifecycle supervisor.
- `radmon/__main__.py` — source/build executable entry point.
- `packaging/RadMon.spec` — PyInstaller `onedir` definition.
- `scripts/build_release.py` — deterministic release assembly/validation/ZIP creation.
- `requirements-dev.txt` — test/build-only dependencies.
- `tests/test_paths.py`
- `tests/test_central_service.py`
- `tests/test_process_ownership.py`
- `tests/test_desktop_app.py`
- `tests/test_production_app.py`
- `tests/test_no_revision_dispatch.py`
- `tests/test_release_layout.py`
- `tests/test_production_docs.py`
- `.github/workflows/windows-release.yml`

**Modify heavily**

- `radmon/config.py`
- `radmon/repository.py`
- `radmon/lan.py`
- `radmon/lan_runtime.py`
- `radmon/remote_alarm.py`
- `radmon/archive_store.py`
- `radmon/archive_reports.py`
- `radmon/security.py`
- `radmon/device_admin.py`
- `radmon/secure_services.py`
- `radmon/secure_context.py`
- `radmon/alarm_policy.py`
- `radmon/alarm_policy_store.py`
- `radmon/grafana_tv.py`
- `radmon/grafana_bootstrap.py`
- `radmon/admin/main_window.py`
- `radmon/admin/station_admin_dialog.py`
- `radmon/admin/alarm_page.py`
- `radmon/admin/alarm_response_dialog.py`
- `radmon/admin/icons.py`
- `radmon/__init__.py`
- `.github/workflows/ci.yml`
- `requirements.txt`
- `README.md`
- `docs/INSTALLATION.md`
- `docs/USER-MANUAL.md`

**Delete only after replacement/parity is proven**

- `RADMON.bat`
- `RUN_DUMMY.bat`
- `RUN_LAN.bat`
- top-level `main.py`
- top-level `central_server.py`
- every `radmon/*_revision.py`
- obsolete tests whose only purpose is parsing/validating old `.bat` files
- zero-reference Silk icon assets and zero-reference Tabler assets
- `scripts/smoke_demo.py` if the final reference scan remains empty
- dated historical design/implementation-plan docs under `docs/`
- this working spec and implementation plan in Task 16

---

### Task 1: Add deterministic source/frozen path resolution

**Files:**
- Create: `radmon/paths.py`
- Create: `tests/test_paths.py`
- Modify: `radmon/config.py`

**Interfaces:**
- Produces: `ApplicationPaths.discover(executable: Path | None = None, *, frozen: bool | None = None) -> ApplicationPaths`.
- Produces properties: `install_root`, `app_dir`, `config_dir`, `runtime_dir`, `archive_dir`, `report_dir`, `log_dir`, `assets_dir`, `grafana_dir`, `env_file`.
- Produces: `ApplicationPaths.asset_path(*parts: str) -> Path`.
- Produces: `Settings.for_application_paths(paths: ApplicationPaths) -> Settings`.
- Consumed by Tasks 3, 4, 5, 10, 13, 15.

- [ ] **Step 1: Write failing source/frozen layout tests**

```python
# tests/test_paths.py
from radmon.paths import ApplicationPaths


def test_source_layout_uses_repository_root(tmp_path, monkeypatch):
    monkeypatch.setattr("radmon.paths._source_root", lambda: tmp_path)
    paths = ApplicationPaths.discover(frozen=False)
    assert paths.install_root == tmp_path
    assert paths.app_dir == tmp_path
    assert paths.config_dir == tmp_path
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.archive_dir == tmp_path / "archives"
    assert paths.report_dir == tmp_path / "reports"
    assert paths.asset_path("manuals", "user-manual.html") == tmp_path / "assets" / "manuals" / "user-manual.html"


def test_frozen_layout_keeps_persistent_data_outside_app(tmp_path):
    exe = tmp_path / "app" / "RadMon.exe"
    paths = ApplicationPaths.discover(executable=exe, frozen=True)
    assert paths.app_dir == tmp_path / "app"
    assert paths.install_root == tmp_path
    assert paths.config_dir == tmp_path / "config"
    assert paths.env_file == tmp_path / "config" / ".env"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.archive_dir == tmp_path / "archives"
    assert paths.report_dir == tmp_path / "reports"
    assert paths.assets_dir == tmp_path / "app" / "assets"
```

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_paths.py`

Expected: import failure because `radmon.paths` does not exist.

- [ ] **Step 3: Implement `ApplicationPaths`**

```python
# radmon/paths.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    install_root: Path
    app_dir: Path
    config_dir: Path
    runtime_dir: Path
    archive_dir: Path
    report_dir: Path
    log_dir: Path
    assets_dir: Path
    grafana_dir: Path

    @property
    def env_file(self) -> Path:
        return self.config_dir / ".env"

    def asset_path(self, *parts: str) -> Path:
        return self.assets_dir.joinpath(*parts)

    @classmethod
    def discover(cls, executable: Path | None = None, *, frozen: bool | None = None) -> "ApplicationPaths":
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if is_frozen:
            app_dir = Path(executable or sys.executable).resolve().parent
            root = app_dir.parent
            return cls(
                install_root=root,
                app_dir=app_dir,
                config_dir=root / "config",
                runtime_dir=root / "runtime",
                archive_dir=root / "archives",
                report_dir=root / "reports",
                log_dir=root / "runtime" / "logs",
                assets_dir=app_dir / "assets",
                grafana_dir=app_dir / "grafana",
            )
        root = _source_root()
        return cls(
            install_root=root,
            app_dir=root,
            config_dir=root,
            runtime_dir=root / "runtime",
            archive_dir=root / "archives",
            report_dir=root / "reports",
            log_dir=root / "logs",
            assets_dir=root / "assets",
            grafana_dir=root / "grafana",
        )
```

- [ ] **Step 4: Make `Settings` path-aware without changing env semantics**

Change `from_env(cls, env_file: str | Path | None = ".env")` and call `load_dotenv(str(env_file), override=False)`. Add `lan_enabled: bool = False`, read `RADMON_LAN_ENABLED`, and add:

```python
def for_application_paths(self, paths: "ApplicationPaths") -> "Settings":
    def resolved(value: Path, default: Path) -> Path:
        if value.is_absolute():
            return value
        default_names = {"runtime", "archives", "logs", "!REPORT!", "reports"}
        return default if str(value) in default_names else paths.install_root / value

    return replace(
        self,
        runtime_dir=resolved(self.runtime_dir, paths.runtime_dir),
        archive_dir=resolved(self.archive_dir, paths.archive_dir),
        report_dir=resolved(self.report_dir, paths.report_dir),
        log_dir=resolved(self.log_dir, paths.log_dir),
    )
```

- [ ] **Step 5: Verify GREEN**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_paths.py tests/test_archive_config.py tests/test_archive_bundle_config.py`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add radmon/paths.py radmon/config.py tests/test_paths.py
git commit -m "feat: add production path resolution"
```

---

### Task 2: Add a managed Uvicorn server primitive

**Files:**
- Create: `radmon/central_service.py`
- Create: `tests/test_central_service.py`

**Interfaces:**
- Produces: `ManagedUvicornServer(app, host: str, port: int)`.
- Produces: `.start(timeout: float = 30.0)`, `.stop(timeout: float = 15.0)`, `.running`.
- Produces: `smoke_server_lifecycle() -> None`.
- Consumed by Task 3 central runtime and Task 13 packaged smoke mode.

- [ ] **Step 1: Write a failing real socket release test**

```python
# tests/test_central_service.py
import socket
from fastapi import FastAPI
from radmon.central_service import ManagedUvicornServer


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_managed_uvicorn_releases_port_after_stop():
    app = FastAPI()
    app.get("/health")(lambda: {"status": "ok"})
    port = _free_port()
    server = ManagedUvicornServer(app, "127.0.0.1", port)
    server.start(timeout=5)
    assert server.running
    server.stop(timeout=5)
    probe = socket.socket()
    try:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        probe.close()
```

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_central_service.py::test_managed_uvicorn_releases_port_after_stop`

Expected: missing class.

- [ ] **Step 3: Implement managed server ownership**

```python
class ManagedUvicornServer:
    def __init__(self, app, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=int(port), reload=False, log_config=None)
        )
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server.started)

    def start(self, timeout: float = 30.0) -> None:
        if self.running:
            return
        self._server.should_exit = False
        self._thread = threading.Thread(target=self._server.run, name="radmon-central-api", daemon=False)
        self._thread.start()
        deadline = time.monotonic() + timeout
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
```

Implement `smoke_server_lifecycle()` with a tiny FastAPI app and ephemeral localhost port, then call start/stop.

- [ ] **Step 4: Verify GREEN and idempotent stop**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_central_service.py`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add radmon/central_service.py tests/test_central_service.py
git commit -m "feat: add managed central server lifecycle"
```

---

### Task 3: Move central runtime construction out of `central_server.py`

**Files:**
- Modify: `radmon/central_service.py`
- Modify temporarily: `central_server.py`
- Modify: `tests/test_central_service.py`
- Regression: `tests/test_central_archive_wiring.py`, `tests/test_secure_api.py`, `tests/test_runtime_status_projection.py`, `tests/test_lan_archive.py`, `tests/test_whatsapp.py`

**Interfaces:**
- Produces dataclass `CentralRuntime(app, services, archive_catalog, lan_runtime)`.
- Produces `build_central_runtime(settings: Settings) -> CentralRuntime`.
- Produces `CentralService(settings: Settings, host="0.0.0.0", port=8090, *, runtime_factory=build_central_runtime, api_factory=ManagedUvicornServer)`.
- `CentralService.start()` starts the LAN runtime before API readiness is returned; failures clean up already-started resources.
- `CentralService.stop()` stops `LanRuntime` before the Uvicorn server and is idempotent.

- [ ] **Step 1: Add a failing order test with complete fakes**

```python
class FakeLanRuntime:
    def __init__(self, events): self.events = events
    def start(self): self.events.append("lan-start")
    def stop(self): self.events.append("lan-stop")


class FakeApi:
    def __init__(self, app, host, port, events): self.events = events
    @property
    def running(self): return True
    def start(self, timeout=30): self.events.append("api-start")
    def stop(self, timeout=15): self.events.append("api-stop")


def test_central_service_stops_lan_before_api():
    events = []
    runtime = SimpleNamespace(app=object(), services=object(), archive_catalog=object(), lan_runtime=FakeLanRuntime(events))
    service = CentralService(
        Settings(lan_enabled=True),
        runtime_factory=lambda settings: runtime,
        api_factory=lambda app, host, port: FakeApi(app, host, port, events),
    )
    service.start()
    service.stop()
    assert events == ["lan-start", "api-start", "lan-stop", "api-stop"]
```

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_central_service.py::test_central_service_stops_lan_before_api`

Expected: missing `CentralService`/runtime interface.

- [ ] **Step 3: Move current `central_server.py` assembly into `build_central_runtime()`**

Preserve this sequence and semantics:

```python
MariaDBRepository(settings).require_schema()
services = build_secure_services(settings)
services.runtime_status_projector.ensure_schema()
services.alarm_policy.restore_and_reconcile_current_state()
archive_catalog = ArchiveCatalog(services.security, settings.archive_dir, timezone_name=settings.archive_timezone)
archive_catalog.reconcile()
# build QuarterArchiveService when settings.archive_enabled
# create_central_app(CentralMariaDBRepository(settings), settings)
# attach_secure_routes(...)
# construct optional WhatsAppAlarmDispatcher
# construct LanRuntime when settings.lan_enabled
return CentralRuntime(app=app, services=services, archive_catalog=archive_catalog, lan_runtime=lan_runtime)
```

- [ ] **Step 4: Implement `CentralService.start/stop` and transitional wrapper**

If API start fails after LAN start, call `lan_runtime.stop()` before re-raising. Reduce `central_server.py` to a temporary delegating wrapper; Task 12 deletes it.

- [ ] **Step 5: Run central regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_central_service.py \
  tests/test_central_archive_wiring.py \
  tests/test_secure_api.py \
  tests/test_runtime_status_projection.py \
  tests/test_lan_archive.py \
  tests/test_whatsapp.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add radmon/central_service.py central_server.py tests/test_central_service.py
git commit -m "refactor: own central runtime in managed service"
```

---

### Task 4: Extract LAN Admin desktop flow from top-level `main.py`

**Files:**
- Create: `radmon/desktop_app.py`
- Create: `tests/test_desktop_app.py`
- Modify temporarily: `main.py`
- Regression: `tests/test_admin_startup_smoke.py`, `tests/test_qt_smoke.py`, `tests/test_station_dialog_lan.py`

**Interfaces:**
- Produces `run_admin_ui(settings: Settings, services: SecureServices, archive_catalog: ArchiveCatalog, log_path: Path) -> int`.
- It does not acquire/release `SingleInstanceLock`.
- It does not start `ApplicationRuntime` or `LanRuntime`.
- It does not call `build_secure_services()` again; it consumes the `SecureServices` already owned by the central runtime.

- [ ] **Step 1: Write a failing ownership test**

```python
from pathlib import Path


def test_desktop_module_does_not_own_central_or_single_instance():
    path = Path("radmon/desktop_app.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "SingleInstanceLock(" not in text
    assert "LanRuntime(" not in text
    assert "ApplicationRuntime(" not in text
    assert "build_secure_services(" not in text
```

- [ ] **Step 2: Verify RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_desktop_app.py`

Expected: file missing.

- [ ] **Step 3: Move existing LAN UI bootstrap/login/window code**

`run_admin_ui()` retains QApplication creation/name, repository schema/station checks, bootstrap-admin/login dialogs and audit, `SecurityContext`, LAN report repositories, `MainWindow(..., source="lan", runtime=None)`, `install_window_security`, and `set_context(None)` on quit.

- [ ] **Step 4: Make `main.py` delegate during transition**

Remove duplicated LAN bootstrap logic from `main.py`; let it call the new production path until Task 12 removes the top-level file.

- [ ] **Step 5: Verify UI regressions**

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_desktop_app.py \
  tests/test_admin_startup_smoke.py \
  tests/test_qt_smoke.py \
  tests/test_station_dialog_lan.py
```

- [ ] **Step 6: Commit**

```bash
git add radmon/desktop_app.py main.py tests/test_desktop_app.py
git commit -m "refactor: extract production desktop entry flow"
```

---

### Task 5: Add safe legacy-process recovery and the single production supervisor

**Files:**
- Create: `radmon/process_ownership.py`
- Create: `tests/test_process_ownership.py`
- Create: `radmon/production_app.py`
- Create: `radmon/__main__.py`
- Create: `tests/test_production_app.py`

**Interfaces:**
- `PortOwner(pid: int, command_line: str)`.
- `find_listener_owner(port: int, runner=subprocess.run) -> PortOwner | None`.
- `is_legacy_radmon_central(owner: PortOwner, port: int) -> bool`.
- `stop_legacy_radmon_central(owner: PortOwner, runner=subprocess.run) -> None`.
- `run_production(paths: ApplicationPaths | None = None, *, central_factory=CentralService, desktop_runner=run_admin_ui, lock_factory=SingleInstanceLock, grafana_startup=...) -> int`.
- `main(argv: Sequence[str] | None = None) -> int` supports `--smoke-test`.

- [ ] **Step 1: Write conservative process classification tests**

```python
from radmon.process_ownership import PortOwner, is_legacy_radmon_central


def test_legacy_central_requires_radmon_script_and_exact_port():
    assert is_legacy_radmon_central(
        PortOwner(42, r'python.exe C:\old\Radmon\central_server.py --host 0.0.0.0 --port 8090'), 8090
    )
    assert not is_legacy_radmon_central(PortOwner(43, r'python.exe other_server.py --port 8090'), 8090)
    assert not is_legacy_radmon_central(
        PortOwner(44, r'python.exe C:\old\Radmon\central_server.py --port 9000'), 8090
    )
```

Add a test asserting `stop_legacy_radmon_central()` raises/refuses before invoking the runner for a foreign owner.

- [ ] **Step 2: Implement Windows inspection without blanket process killing**

Use explicit PowerShell argument arrays for `Get-NetTCPConnection`, `Get-CimInstance Win32_Process`, and `Stop-Process -Id`. Never use `taskkill /IM python.exe`.

- [ ] **Step 3: Write failing supervisor order/cleanup tests with complete fakes**

```python
class FakeLock:
    def __init__(self, events): self.events = events
    def acquire(self): self.events.append("lock"); return True
    def release(self): self.events.append("unlock")


class FakeCentral:
    def __init__(self, events):
        self.events = events
        self.services = object()
        self.archive_catalog = object()
    def start(self): self.events.append("central-start")
    def stop(self): self.events.append("central-stop")


def test_supervisor_stops_central_when_desktop_exits(tmp_path):
    events = []
    paths = ApplicationPaths(
        tmp_path, tmp_path, tmp_path / "config", tmp_path / "runtime",
        tmp_path / "archives", tmp_path / "reports", tmp_path / "logs",
        tmp_path / "assets", tmp_path / "grafana",
    )
    central = FakeCentral(events)
    code = run_production(
        paths=paths,
        central_factory=lambda *a, **k: central,
        desktop_runner=lambda *a, **k: events.append("desktop") or 0,
        lock_factory=lambda port: FakeLock(events),
        grafana_startup=lambda *a, **k: events.append("grafana"),
        listener_owner=lambda port: None,
    )
    assert code == 0
    assert events == ["lock", "central-start", "grafana", "desktop", "central-stop", "unlock"]
```

Add a second test where `desktop_runner` raises; `central-stop` and `unlock` must still occur.

- [ ] **Step 4: Implement production lifecycle with `try/finally`**

Core order:

```python
paths = paths or ApplicationPaths.discover()
for folder in (paths.config_dir, paths.runtime_dir, paths.archive_dir, paths.report_dir, paths.log_dir):
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
    return desktop_runner(settings, central.services, central.archive_catalog, log_path)
finally:
    if central is not None:
        central.stop()
    lock.release()
```

The single-instance lock check happens before stale-port recovery so a second active new RadMon instance is never mistaken for stale ownership.

- [ ] **Step 5: Add `radmon/__main__.py` and smoke mode entry**

`python -m radmon` calls `production_app.main()`. `--smoke-test` resolves paths, validates packaged imports/resources, calls `smoke_server_lifecycle()`, prints one success line, and exits 0 without production DB access.

- [ ] **Step 6: Verify targeted tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_process_ownership.py \
  tests/test_production_app.py \
  tests/test_central_service.py
```

- [ ] **Step 7: Commit**

```bash
git add radmon/process_ownership.py radmon/production_app.py radmon/__main__.py tests/test_process_ownership.py tests/test_production_app.py
git commit -m "feat: add single production supervisor"
```

---

### Task 6: Consolidate repository and archive revision behavior

**Files:**
- Modify: `radmon/repository.py`
- Modify: `radmon/archive_store.py`
- Modify: `radmon/archive_reports.py`
- Modify: `radmon/__init__.py`
- Create: `tests/test_no_revision_dispatch.py`
- Regression: `tests/test_repository_contract.py`, `tests/test_legacy_schema_runtime.py`, `tests/test_archive.py`, `tests/test_archive_reports.py`, `tests/test_archive_report_boundaries.py`, `tests/test_archive_reconcile_reports.py`
- Delete after parity: `radmon/repository_revision.py`, `radmon/archive_store_revision.py`, `radmon/archive_reports_revision.py`

**Interfaces:**
- `MariaDBRepository.validate_schema/live_rows/latest_reading/insert_measurement/alarm_history/last_alarm/record_alarm/append_log` are defined by `radmon.repository`.
- `CentralArchiveStore.monthly_recap_rows` directly normalizes production `dtoa/lvl` alarm fields.
- `ArchiveReportRepository.alarm_history` directly reads production alarm CSV fields.

- [ ] **Step 1: Add failing module-origin tests**

```python
from radmon.repository import MariaDBRepository
from radmon.archive_store import CentralArchiveStore
from radmon.archive_reports import ArchiveReportRepository


def test_repository_and_archive_behavior_is_not_monkey_patched():
    assert MariaDBRepository.live_rows.__module__ == "radmon.repository"
    assert CentralArchiveStore.monthly_recap_rows.__module__ == "radmon.archive_store"
    assert ArchiveReportRepository.alarm_history.__module__ == "radmon.archive_reports"
```

- [ ] **Step 2: Verify RED, then move final behavior exactly**

Move the existing final bodies from `repository_revision.py` for `production_schema`, `validate_schema`, `live_rows`, `latest_reading`, `insert_measurement`, `alarm_history`, `last_alarm`, `record_alarm`, `append_log` into `repository.py`. Move production `TABLE_COLUMNS/TIME_COLUMNS` and alarm recap normalization from `archive_store_revision.py` into `archive_store.py`. Move `ArchiveReportRepository.alarm_history` from `archive_reports_revision.py` into `archive_reports.py`.

Do not change SQL semantics in this task; it is consolidation only.

- [ ] **Step 3: Remove only these three apply calls from `radmon/__init__.py` and run parity**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_no_revision_dispatch.py \
  tests/test_repository_contract.py \
  tests/test_legacy_schema_runtime.py \
  tests/test_archive.py \
  tests/test_archive_reports.py \
  tests/test_archive_report_boundaries.py \
  tests/test_archive_reconcile_reports.py
```

- [ ] **Step 4: Delete consolidated files and commit**

```bash
git rm radmon/repository_revision.py radmon/archive_store_revision.py radmon/archive_reports_revision.py
git add radmon/repository.py radmon/archive_store.py radmon/archive_reports.py radmon/__init__.py tests/test_no_revision_dispatch.py
git commit -m "refactor: consolidate repository and archive patches"
```

---

### Task 7: Consolidate LAN, remote-alarm, and production safety behavior

**Files:**
- Modify: `radmon/lan.py`
- Modify: `radmon/lan_runtime.py`
- Modify: `radmon/remote_alarm.py`
- Modify: `radmon/secure_services.py`
- Modify: `radmon/secure_context.py`
- Modify: `radmon/__init__.py`
- Modify: `tests/test_no_revision_dispatch.py`
- Regression: `tests/test_lan.py`, `tests/test_lan_ownership.py`, `tests/test_remote_alarm.py`, `tests/test_production_safety_guards.py`, `tests/test_production_source_safety.py`, `tests/test_source_health.py`
- Delete after parity: `radmon/lan_revision.py`, `radmon/remote_alarm_revision.py`, `radmon/production_safety_revision.py`

**Interfaces:**
- `RemoteMariaDBSource` directly owns `live_rows`, `alarms_after`, `active_alarm_keys`, `get_device`, `update_device`, `respond_alarm`, `alarm_states`.
- `LanCheckpointStore` directly owns alarm checkpoint schema/load/save.
- `MariaCentralStore` directly owns live upsert, measurement import, alarm mirror, handled-marker update.
- `LanAggregator` directly owns final live/backfill/source cycles including active-set reconciliation and alarm-policy hook points.
- `RemoteAlarmMirror` directly owns production mirroring and active-key reconciliation.

- [ ] **Step 1: Add failing origin checks**

```python
from radmon.lan import RemoteMariaDBSource, LanAggregator, MariaCentralStore
from radmon.remote_alarm import RemoteAlarmMirror


def test_lan_alarm_behavior_is_defined_in_base_modules():
    assert RemoteMariaDBSource.live_rows.__module__ == "radmon.lan"
    assert LanAggregator.run_live_once.__module__ == "radmon.lan"
    assert MariaCentralStore.mark_alarm_handled.__module__ == "radmon.lan"
    assert RemoteAlarmMirror.mirror.__module__ == "radmon.remote_alarm"
```

- [ ] **Step 2: Fold `lan_revision.py` into `lan.py`**

Move `LIVE_KEYS`, `LivePullResult`, `BackfillPullResult`, live/alarm polling, alarm checkpoints, central live/measurement/alarm writes, `run_live_once`, `run_backfill_once`, and compatibility `run_source_once` into the actual classes.

- [ ] **Step 3: Fold remote mirror and active state handling into `remote_alarm.py`**

The final `mirror()` preserves `remote_serid`, `i_flag/i_op/pic/note`, historical/already-notified semantics, `is_active`, and notification idempotency. Integrate `ensure_active_schema`, `get`, `mark_acknowledged`, and `reconcile_source_active_keys` as normal class methods rather than runtime assignments.

- [ ] **Step 4: Fold source safety behavior directly**

Implement `RemoteMariaDBSource.active_alarm_keys()` as compact `serid,dtoa WHERE i_flag=0`, `MariaCentralStore.mark_alarm_handled()`, and final active-key reconciliation in `LanAggregator.run_live_once()`.

- [ ] **Step 5: Replace env-only source-write authorization with `settings.lan_enabled`**

`build_secure_services(settings)` enables station source write-through only when `settings.lan_enabled` is true. Defining LAN endpoints without LAN runtime enablement must not authorize writes.

- [ ] **Step 6: Move sensitive-lease clearing into `secure_context.set_context()`**

Before identity replacement/clear, call `current.security.clear_sensitive_lease(current.identity.username)` in the existing exception-safe path.

- [ ] **Step 7: Remove apply calls, run parity, delete revisions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_no_revision_dispatch.py \
  tests/test_lan.py \
  tests/test_lan_ownership.py \
  tests/test_remote_alarm.py \
  tests/test_production_safety_guards.py \
  tests/test_production_source_safety.py \
  tests/test_source_health.py

git rm radmon/lan_revision.py radmon/remote_alarm_revision.py radmon/production_safety_revision.py
git add radmon/lan.py radmon/lan_runtime.py radmon/remote_alarm.py radmon/secure_services.py radmon/secure_context.py radmon/__init__.py tests/test_no_revision_dispatch.py
git commit -m "refactor: consolidate LAN and alarm safety patches"
```

---

### Task 8: Consolidate security, station write-through, ACK, and production compatibility behavior

**Files:**
- Modify: `radmon/security.py`
- Modify: `radmon/device_admin.py`
- Modify: `radmon/secure_services.py`
- Modify: `radmon/remote_alarm.py`
- Modify: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/__init__.py`
- Modify: `tests/test_no_revision_dispatch.py`
- Regression: `tests/test_security.py`, `tests/test_device_admin.py`, `tests/test_production_integration_fix.py`, `tests/test_station_dialog_lan.py`, `tests/test_remote_alarm.py`
- Delete after parity: `radmon/production_integration_compat_revision.py`

**Interfaces:**
- `SecurityStore.sensitive_lease_active`, `clear_sensitive_lease`, `require_sensitive`, `station_source`, `station_source_map` live directly in `security.py`.
- Explicitly supplied bad PIN always fails even while a sensitive lease is active; empty PIN may reuse a valid lease.
- `DeviceAdminService(..., station_source=None, remote_factory=None, write_through=False)` supports LAN source write-through directly.
- `AlarmControlService.ack()` uses `respond_alarm()` in production (`i_op/pic/note/i_flag=1`, preserve `ack`) and permits `ack_legacy()` only for synthetic non-`RemoteMariaDBSource` adapters.
- LAN Station Properties disables SERID and hardware identity fields.

- [ ] **Step 1: Add failing origin and explicit-bad-PIN tests**

```python
from radmon.security import SecurityStore
from radmon.device_admin import DeviceAdminService
from radmon.remote_alarm import AlarmControlService


def test_security_write_through_and_ack_are_defined_in_base_modules():
    assert SecurityStore.require_sensitive.__module__ == "radmon.security"
    assert DeviceAdminService.update_station.__module__ == "radmon.device_admin"
    assert AlarmControlService.ack.__module__ == "radmon.remote_alarm"
```

In `tests/test_security.py`, establish a valid lease, then call `require_sensitive(identity, permission, "wrong-pin")` and assert `SecurityError`.

- [ ] **Step 2: Move final SecurityStore lease/mapping behavior into `security.py`**

Initialize `_sensitive_leases` and `_sensitive_lease_lock` in `__init__`; clear leases on user disable, PIN reset, and session revoke; implement unique source mapping and ambiguous mapping error.

- [ ] **Step 3: Move final remote source and DeviceAdmin behavior**

Keep exactly this LAN editable set:

```python
LAN_EDITABLE_FIELDS = {
    "name", "location", "description", "warnlevel", "alarmlevel",
    "maxidlemin", "unit", "audiopath",
}
```

Hardware/source identity remains immutable in LAN mode.

- [ ] **Step 4: Move final ACK behavior into `AlarmControlService.ack()`**

Preserve existing success/failure audit records and do not fall back to `ack=1` for deployed `RemoteMariaDBSource`.

- [ ] **Step 5: Integrate LAN identity-field disablement into the existing StationAdminDialog constructor**

Use the existing widget constructor and add only:

```python
if source == "lan":
    self.serid.setEnabled(False)
    self.hw_type.setEnabled(False)
    self.hw_address.setEnabled(False)
```

Do not retain a copied duplicate constructor from the compatibility patch.

- [ ] **Step 6: Verify parity, delete patch, commit**

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_no_revision_dispatch.py \
  tests/test_security.py \
  tests/test_device_admin.py \
  tests/test_remote_alarm.py \
  tests/test_production_integration_fix.py \
  tests/test_station_dialog_lan.py

git rm radmon/production_integration_compat_revision.py
git add radmon/security.py radmon/device_admin.py radmon/secure_services.py radmon/remote_alarm.py radmon/admin/station_admin_dialog.py radmon/__init__.py tests/test_no_revision_dispatch.py
git commit -m "refactor: consolidate production security integration"
```

---

### Task 9: Consolidate Alarm Policy store/runtime/security integration

**Files:**
- Modify: `radmon/alarm_policy.py`
- Modify: `radmon/alarm_policy_store.py`
- Modify: `radmon/security.py`
- Modify: `radmon/remote_alarm.py`
- Modify: `radmon/lan.py`
- Modify: `radmon/lan_runtime.py`
- Modify: `radmon/__init__.py`
- Modify: `tests/test_no_revision_dispatch.py`
- Regression: all `tests/test_alarm_policy*.py`, `tests/test_alarm_suppression.py`, `tests/test_alarm_suppression_ui.py`, `tests/test_whatsapp.py`
- Delete after parity: `radmon/alarm_policy_revision.py`, `alarm_policy_store_revision.py`, `alarm_policy_security_revision.py`, `alarm_policy_runtime_revision.py`

**Interfaces:**
- Admin and Operator have `suppress_alarm`; Viewer does not.
- `AlarmPolicyStore.start_suppression(..., connection=None)` reads its inserted row through the same supplied SQLite transaction.
- `AlarmPolicyService` directly owns current snapshot cache, restart notification gate, final `get_policy/list_events/process_cycle`, source alarm annotation, and source-silence retry.
- Source-silence retry remains max 25 rows/cycle with delays `(5, 15, 30, 60)` capped at 60.
- Silence decisions remain exactly `SUPPRESSED`, `RETRIGGER_LOCKED`, `COALESCED_DUPLICATE`.

- [ ] **Step 1: Add failing origin/permission tests**

```python
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.security import ROLE_PERMISSIONS, Role


def test_alarm_policy_is_defined_in_final_modules():
    assert AlarmPolicyService.get_policy.__module__ == "radmon.alarm_policy"
    assert AlarmPolicyStore.start_suppression.__module__ == "radmon.alarm_policy_store"
    assert "suppress_alarm" in ROLE_PERMISSIONS[Role.ADMINISTRATOR]
    assert "suppress_alarm" in ROLE_PERMISSIONS[Role.OPERATOR]
    assert "suppress_alarm" not in ROLE_PERMISSIONS[Role.VIEWER]
```

- [ ] **Step 2: Integrate same-transaction suppression readback directly**

Use the exact insert/select/commit/rollback semantics currently in `alarm_policy_store_revision.py`, but define the method in `alarm_policy_store.py`.

- [ ] **Step 3: Integrate runtime snapshot and notification gate**

Initialize:

```python
self._current_policy_snapshots: dict[int, dict[str, Any]] = {}
self.notifications_enabled = False
```

`_snapshot()` updates the cache; `get_policy()` merges live + persistent state; `list_events(notify_pending_only=True)` returns no pending notifications until a completed fresh `process_cycle()` sets the gate true.

- [ ] **Step 4: Integrate source annotation, response, and bounded silence retry**

Move `_pending_alarm_rows`, `_mapped_live_rows`, `_retry_source_silences`, mirror policy helpers, `AlarmControlService.silence_source_row/respond_policy_event`, and aggregator policy wiring into their natural classes. Keep the existing central SQLite retry column/state and source response semantics.

- [ ] **Step 5: Define suppression permission directly in role constants**

Do not mutate `ROLE_PERMISSIONS` at import time.

- [ ] **Step 6: Verify parity, delete four revisions, commit**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_alarm_policy.py \
  tests/test_alarm_policy_api.py \
  tests/test_alarm_policy_integration.py \
  tests/test_alarm_policy_notifications.py \
  tests/test_alarm_policy_resilience.py \
  tests/test_alarm_policy_snapshot.py \
  tests/test_alarm_policy_source_retry.py \
  tests/test_alarm_policy_store.py \
  tests/test_alarm_suppression.py \
  tests/test_whatsapp.py \
  tests/test_no_revision_dispatch.py

git rm radmon/alarm_policy_revision.py radmon/alarm_policy_store_revision.py radmon/alarm_policy_security_revision.py radmon/alarm_policy_runtime_revision.py
git add radmon/alarm_policy.py radmon/alarm_policy_store.py radmon/security.py radmon/remote_alarm.py radmon/lan.py radmon/lan_runtime.py radmon/__init__.py tests/test_no_revision_dispatch.py
git commit -m "refactor: consolidate alarm policy patches"
```

---

### Task 10: Consolidate desktop integration and semantic assets; remove Silk compatibility

**Files:**
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/alarm_response_dialog.py`
- Modify: `radmon/admin/icons.py`
- Create/move: `assets/icons/tabler/` containing only referenced Tabler SVGs plus license
- Create/move: `assets/manuals/installation.html`, `assets/manuals/user-manual.html`, `assets/manuals/manual.css`
- Modify: `radmon/__init__.py`
- Regression: `tests/test_admin_ui_v3.py`, `tests/test_icon_registry.py`, `tests/test_production_integration_fix.py`, `tests/test_legacy_ui_parity.py`, `tests/test_alarm_suppression_ui.py`
- Delete after parity: `radmon/icon_system_revision.py`, `radmon/admin/icons/silk/`

**Interfaces:**
- `app_icon(slot, paths: ApplicationPaths | None = None) -> QIcon` resolves packaged/source `assets/icons/tabler`.
- MainWindow directly owns source grouping/sidebar state, manual actions, refresh/alarm beep integration, and semantic station icons.
- StationAdminDialog directly sets `app_icon("station_properties")`.
- Alarm UI wording remains `Response / Silence` and `Alarm Response / Silence`.

- [ ] **Step 1: Add failing zero-Silk tests**

Extend `test_icon_registry.py` to scan `radmon/admin/*.py` and assert `silk_icon(` / `silk_path(` are absent. Assert every `ICON_SLOTS` value has `assets/icons/tabler/<id>.svg`.

- [ ] **Step 2: Integrate UI behavior from production/icon revisions directly**

Use `app_icon("station_group")`, `app_icon("detector")`, `app_icon("station_properties")` in base methods. Integrate existing source grouping, manual opening, source parent state, refresh, and alarm beep behavior into `MainWindow` methods rather than runtime wrappers.

- [ ] **Step 3: Move manuals and required Tabler assets into `assets/`**

Required SVG set is exactly `{f"{icon_id}.svg" for icon_id in ICON_SLOTS.values()}`. Preserve the Tabler license in the distributed assets. Move current manual HTML/CSS content unchanged first; Task 15 rewrites content.

- [ ] **Step 4: Remove Silk API/assets and icon patch**

Delete `_SILK_ROOT`, `silk_path`, `silk_icon` and the Silk directory only after the zero-reference test passes. Delete `icon_system_revision.py` and remove its apply call.

- [ ] **Step 5: Run UI parity and commit**

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_admin_ui_v3.py \
  tests/test_icon_registry.py \
  tests/test_production_integration_fix.py \
  tests/test_legacy_ui_parity.py \
  tests/test_alarm_suppression_ui.py

git add radmon/admin assets tests/test_icon_registry.py tests/test_admin_ui_v3.py radmon/__init__.py
git rm -r radmon/admin/icons/silk
git rm radmon/icon_system_revision.py
git commit -m "refactor: consolidate desktop integration and assets"
```

---

### Task 11: Consolidate Grafana production/WIB/policy/bootstrap revisions

**Files:**
- Modify: `radmon/grafana_tv.py`
- Modify: `radmon/grafana_bootstrap.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/__init__.py`
- Modify: `tests/test_no_revision_dispatch.py`
- Regression: every `tests/test_grafana*.py`, `tests/test_monitoring_chart_direct_main.py`, `tests/test_cleanup_chart_monitoring_v4.py`
- Delete after parity: `radmon/grafana_revision.py`, `grafana_bootstrap_revision.py`, `grafana_wib_revision.py`, `grafana_policy_revision.py`; delete `production_integration_revision.py` once its non-Grafana sections have also been moved by Tasks 7, 8, and 10.

**Interfaces:**
- Final `grafana_tv.py` directly owns production header/latest/status, explicit WIB epoch conversion, policy runtime-status join, operation table, dose sparklines, building trends, and final page-three alarm query.
- Final `GrafanaBootstrap.ensure()` reprovisions a healthy/ready real Grafana before reuse while preserving fast reuse for synthetic/custom probes without `/api/health`.
- Native-before-Docker fallback remains.

- [ ] **Step 1: Add failing origin tests**

```python
from radmon import grafana_tv
from radmon.grafana_bootstrap import GrafanaBootstrap


def test_grafana_final_builders_are_not_revision_patched():
    assert grafana_tv._status_relation.__module__ == "radmon.grafana_tv"
    assert grafana_tv._operation_table.__module__ == "radmon.grafana_tv"
    assert GrafanaBootstrap.ensure.__module__ == "radmon.grafana_bootstrap"
```

- [ ] **Step 2: Fold patch order into one direct final implementation**

The final `_status_relation()` must include both explicit WIB idle-age logic and policy projection:

```sql
LEFT JOIN radmon_runtime_status r ON r.serid = v.serid
...
WHEN TIMESTAMPDIFF(SECOND, v.dtom, CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')) > COALESCE(v.maxidlemin, 30) * 60 THEN 'OFFLINE'
WHEN COALESCE(r.suppressed, 0) = 1 THEN 'SUPPRESSED'
```

Historical time-series filters use explicit `CONVERT_TZ(... '+07:00' -> '+00:00')` epoch expressions, not raw `$__timeFilter(dtom)`.

- [ ] **Step 3: Integrate healthy-ready reprovisioning into `GrafanaBootstrap.ensure()`**

Use the current `grafana_bootstrap_revision.py` behavior as normal code; remove the `_radmon_reprovision_patch` marker mechanism.

- [ ] **Step 4: Remove Grafana revision apply calls/files and finish `production_integration_revision.py` removal**

Before deleting `production_integration_revision.py`, confirm all `_patch_security`, `_patch_remote_source`, `_patch_device_admin`, `_patch_secure_services`, `_patch_alarm_mirror_and_control`, `_patch_live_collector`, `_patch_admin_ui`, and `_patch_grafana` behavior now exists directly in base modules.

- [ ] **Step 5: Run Grafana matrix**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_grafana_alarm_policy.py \
  tests/test_grafana_bootstrap_fast_open.py \
  tests/test_grafana_bootstrap_playlist.py \
  tests/test_grafana_monitoring.py \
  tests/test_grafana_reprovision.py \
  tests/test_grafana_revision.py \
  tests/test_grafana_tv.py \
  tests/test_grafana_tv_visibility.py \
  tests/test_grafana_wib_time.py \
  tests/test_monitoring_chart_direct_main.py \
  tests/test_cleanup_chart_monitoring_v4.py \
  tests/test_no_revision_dispatch.py
```

- [ ] **Step 6: Delete files and commit**

```bash
git rm radmon/grafana_revision.py radmon/grafana_bootstrap_revision.py radmon/grafana_wib_revision.py radmon/grafana_policy_revision.py radmon/production_integration_revision.py
git add radmon/grafana_tv.py radmon/grafana_bootstrap.py radmon/admin/main_window.py radmon/__init__.py tests/test_no_revision_dispatch.py
git commit -m "refactor: remove runtime revision patch layer"
```

---

### Task 12: Remove old launchers/entry points and enforce a clean source structure

**Files:**
- Modify: `radmon/__init__.py`
- Delete: any remaining `radmon/*_revision.py`
- Delete: `RADMON.bat`, `RUN_DUMMY.bat`, `RUN_LAN.bat`
- Delete: top-level `main.py`, `central_server.py`
- Delete: `tests/test_run_lan_launcher.py`, `tests/test_windows_launchers.py`
- Modify: `tests/test_windows_launcher_timezone.py`, `tests/test_runtime_v2.py`, `tests/test_lan_ownership.py`
- Delete: `scripts/smoke_demo.py` only if final `git grep` still shows no runtime/build consumer
- Delete: dated historical `docs/2026-09-*` engineering docs, except the working superpowers spec/plan until Task 16.

**Interfaces:**
- `radmon/__init__.py` has package metadata only; importing `radmon` has no runtime patch side effects.
- Source entry point is `python -m radmon`; production entry point is compiled `RadMon.exe`.

- [ ] **Step 1: Turn `test_no_revision_dispatch.py` into final structural contract**

```python
from pathlib import Path


def test_package_has_no_revision_patch_modules_or_batch_launchers():
    root = Path(__file__).resolve().parents[1]
    assert not list((root / "radmon").glob("*_revision.py"))
    assert not list(root.glob("*.bat"))
    init_text = (root / "radmon" / "__init__.py").read_text(encoding="utf-8")
    assert "_revision" not in init_text
    assert "apply()" not in init_text
```

- [ ] **Step 2: Replace launcher-source tests with supervisor tests**

In `test_runtime_v2.py`, assert no root `.bat` files and assert `radmon/__main__.py` exists. In `test_lan_ownership.py`, assert central ownership through `ProductionApplication/CentralService`, not batch source strings. Change timezone test to assert `tzdata` remains in requirements and `Settings.from_env()` can resolve `Asia/Jakarta`; stop inspecting batch scripts.

- [ ] **Step 3: Delete obsolete files and make `radmon/__init__.py` minimal**

```python
"""Radiation Monitoring System for DPFK."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Run dead-reference scan before deleting helper scripts**

```bash
git grep -n "smoke_demo\|RADMON.bat\|RUN_DUMMY.bat\|RUN_LAN.bat\|central_server.py\|_revision" -- ':!docs/superpowers/*'
```

Any remaining hit must be either an absence-test assertion or operational docs to rewrite in Task 15. Do not delete a file with an active runtime/build consumer.

- [ ] **Step 5: Run complete source suite**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`

Expected: zero failures.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "cleanup: remove obsolete launchers and patch layer"
```

---

### Task 13: Add PyInstaller `onedir` packaging and deterministic release validation

**Files:**
- Create: `packaging/RadMon.spec`
- Create: `scripts/build_release.py`
- Create: `tests/test_release_layout.py`
- Create: `requirements-dev.txt`
- Modify: `requirements.txt`
- Modify: `.gitignore`

**Interfaces:**
- `python scripts/build_release.py --output dist-release` builds `dist-release/app/RadMon.exe`, `_internal/`, `assets/`, Grafana resources, `.env.example`, and a versioned ZIP.
- `python scripts/build_release.py --validate-only dist-release` validates layout without rebuilding.
- Release must never include production `.env`, `.bat`, top-level Python launchers, tests, or historical engineering docs.

- [ ] **Step 1: Write failing layout validator tests**

```python
from scripts.build_release import validate_release_layout


def test_release_layout_requires_exe_and_rejects_source(tmp_path):
    app = tmp_path / "app"
    app.mkdir(parents=True)
    (app / "main.py").write_text("bad", encoding="utf-8")
    errors = validate_release_layout(tmp_path)
    assert "missing app/RadMon.exe" in errors
    assert "source file shipped: app/main.py" in errors


def test_release_layout_rejects_secret_env_and_batch(tmp_path):
    app = tmp_path / "app"
    app.mkdir(parents=True)
    (app / "RadMon.exe").write_bytes(b"MZ")
    (app / ".env").write_text("secret=1", encoding="utf-8")
    (app / "run.bat").write_text("echo bad", encoding="utf-8")
    errors = validate_release_layout(tmp_path)
    assert any(".env" in item for item in errors)
    assert any(".bat" in item for item in errors)
```

- [ ] **Step 2: Run RED**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_release_layout.py`

- [ ] **Step 3: Split runtime/dev dependencies**

Remove `pytest` from runtime `requirements.txt`. Create:

```text
-r requirements.txt
pytest>=8,<10
pyyaml>=6,<7
pyinstaller>=6.10,<7
```

- [ ] **Step 4: Create `packaging/RadMon.spec`**

Use entry `radmon/__main__.py`, executable name `RadMon`, `console=False`, and include only required data:

```python
datas = [
    ("assets", "assets"),
    ("grafana", "grafana"),
    (".env.example", "."),
]
```

Add hidden imports only when a real Windows PyInstaller build proves one is required.

- [ ] **Step 5: Implement build/validation script**

Run PyInstaller with:

```python
subprocess.run([
    sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/RadMon.spec"
], check=True)
```

Copy the resulting onedir payload to `<output>/app`, validate forbidden names/suffixes, then create `RadMon-<version>-windows-x64.zip` with `zipfile`.

Validator forbidden rules include:

```python
FORBIDDEN_SUFFIXES = {".bat"}
FORBIDDEN_NAMES = {"main.py", "central_server.py", ".env"}
```

and reject `tests/`, dated engineering docs, or shipped source `.py` files in the release payload.

- [ ] **Step 6: Verify GREEN and commit**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_release_layout.py
git add packaging/RadMon.spec scripts/build_release.py tests/test_release_layout.py requirements.txt requirements-dev.txt .gitignore
git commit -m "build: add Windows onedir release packaging"
```

---

### Task 14: Add Linux source CI and Windows packaged-release verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/windows-release.yml`

**Interfaces:**
- Linux CI installs `requirements-dev.txt`, runs full pytest, compile validation, and Grafana payload/YAML validation.
- Windows CI builds the PyInstaller release, validates layout, runs `RadMon.exe --smoke-test`, and uploads the versioned ZIP.

- [ ] **Step 1: Update Linux CI**

Install `requirements-dev.txt`; compile `radmon scripts` instead of deleted top-level entry scripts. Keep Grafana payload/YAML validation.

- [ ] **Step 2: Create Windows workflow**

Required job body:

```yaml
- name: Run source tests
  shell: pwsh
  run: |
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
    $env:QT_QPA_PLATFORM="offscreen"
    python -m pytest -q

- name: Build release
  run: python scripts/build_release.py --output dist-release

- name: Packaged smoke test
  shell: pwsh
  run: .\dist-release\app\RadMon.exe --smoke-test

- name: Validate release layout
  run: python scripts/build_release.py --validate-only dist-release
```

Use `actions/upload-artifact@v4` for only the generated versioned ZIP.

- [ ] **Step 3: Commit/push and require green workflows**

```bash
git add .github/workflows/ci.yml .github/workflows/windows-release.yml
git commit -m "ci: verify Windows RadMon release"
git push -u origin release-cleanup
```

Do not proceed past a red workflow; inspect the failing job log, reproduce the actual failure, add/fix the relevant test, then push a corrective commit.

---

### Task 15: Rewrite current operational documentation for executable deployment

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTALLATION.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `assets/manuals/installation.html`
- Modify: `assets/manuals/user-manual.html`
- Modify: `assets/manuals/manual.css` only where navigation/path changes require it
- Create: `tests/test_production_docs.py`

**Interfaces:**
- Production SOP uses only `RadMon.exe` for start/stop.
- Upgrade replaces only `C:\RadMon\app\` and preserves `config/.env`, `runtime/`, `archives/`, `reports/`.
- Rollback restores `backup\app-previous\` without changing persistent state.

- [ ] **Step 1: Write failing documentation guard**

```python
from pathlib import Path


def test_production_docs_use_executable_sop_only():
    text = "\n".join([
        Path("README.md").read_text(encoding="utf-8"),
        Path("docs/INSTALLATION.md").read_text(encoding="utf-8"),
        Path("docs/USER-MANUAL.md").read_text(encoding="utf-8"),
    ])
    for obsolete in ("RUN_LAN.bat", "RUN_DUMMY.bat", "RADMON.bat"):
        assert obsolete not in text
    assert "RadMon.exe" in text
    assert r"C:\RadMon\app" in text
    assert r"C:\RadMon\config\.env" in text
```

- [ ] **Step 2: Rewrite Markdown operational docs**

Document initial folder install, config creation from `.env.example`, external Grafana expectation/fallback, start/stop, diagnostics, upgrade, rollback, stable source IDs, and explicit no-source-DB-migration guarantee. Remove production instructions for Git, virtualenv, pip, pytest, batch launchers, and top-level Python scripts.

- [ ] **Step 3: Rewrite packaged HTML help to the same SOP**

Keep product-help content accessible through MainWindow paths under `assets/manuals/`.

- [ ] **Step 4: Verify docs/UI**

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_production_docs.py \
  tests/test_production_integration_fix.py \
  tests/test_admin_ui_v3.py
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/INSTALLATION.md docs/USER-MANUAL.md assets/manuals tests/test_production_docs.py
git commit -m "docs: switch production SOP to RadMon executable"
```

---

### Task 16: Final verification, production commissioning gate, and removal of working engineering docs

**Files:**
- Delete after all verification is green: `docs/superpowers/specs/2026-09-12-radmon-production-release-cleanup-design.md`
- Delete after all verification is green: `docs/superpowers/plans/2026-09-12-radmon-production-release-cleanup.md`
- Delete newly empty directories.
- Any regression discovered here must be fixed in the owning module with a failing test before returning to final verification.

**Interfaces:**
- Final source tree contains no `*_revision.py`, root `.bat`, top-level `main.py`, top-level `central_server.py`, or historical engineering design/plan docs.
- Final release contains `app/RadMon.exe` and no source secrets/launchers/tests.

- [ ] **Step 1: Run structural checks**

```bash
test -z "$(find radmon -maxdepth 1 -name '*_revision.py' -print)"
test -z "$(find . -maxdepth 1 -name '*.bat' -print)"
test ! -e main.py
test ! -e central_server.py
python -m compileall -q radmon scripts
```

Use equivalent PowerShell assertions on Windows.

- [ ] **Step 2: Run the complete source suite from a clean worktree**

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 3: Run lifecycle/release targets again**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_paths.py \
  tests/test_central_service.py \
  tests/test_process_ownership.py \
  tests/test_production_app.py \
  tests/test_release_layout.py
```

Expected: zero failures.

- [ ] **Step 4: Require green GitHub Actions and inspect the Windows ZIP**

Both source CI and Windows release workflow must conclude `success`. Inspect artifact contents and require:

```text
app/RadMon.exe                 present
app/_internal/                 present
app/assets/                    present
app/.env.example               present
*.bat                          absent
app/.env                       absent
main.py                        absent
central_server.py              absent
tests/                         absent
historical engineering docs    absent
```

The workflow must have executed `RadMon.exe --smoke-test`; build success alone is not sufficient evidence.

- [ ] **Step 5: Physical production commissioning gate**

On the central PC preserve production config/state, install the new `app/` beside `backup/app-previous/`, then validate real source reachability/polling, source write-through/response, Grafana, restart, suppression/NORMAL reset, archive/report behavior, and optional WhatsApp session. After closing the GUI run:

```powershell
Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
```

Expected: no output. Also confirm no RadMon-owned orphan process remains.

- [ ] **Step 6: Remove the working spec and plan only after all verification is green**

```bash
git rm docs/superpowers/specs/2026-09-12-radmon-production-release-cleanup-design.md
git rm docs/superpowers/plans/2026-09-12-radmon-production-release-cleanup.md
```

- [ ] **Step 7: Final cleanup commit**

```bash
git add -A
git commit -m "chore: finalize production release cleanup"
```

- [ ] **Step 8: Compare against main before merge**

```bash
git status --short
git diff --check main...release-cleanup
git diff --stat main...release-cleanup
```

Expected: clean working tree, no whitespace errors, and only intentional production cleanup/release changes. Merge to `main` only after source CI, Windows package CI, artifact inspection, and physical commissioning evidence are accepted.
