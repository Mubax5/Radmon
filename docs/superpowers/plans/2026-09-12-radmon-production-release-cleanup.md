# RadMon Production Release Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-oriented Windows x64 RadMon release where operators launch only `RadMon.exe`, closing the UI shuts down all RadMon-owned central services, and the repository no longer contains obsolete launchers, runtime monkey-patch revision modules, dead assets/scripts, or historical engineering documents.

**Architecture:** Introduce explicit packaged/development path resolution, a managed central-service wrapper, and a production application supervisor that owns the full lifecycle of FastAPI/Uvicorn, LAN runtime, optional WhatsApp resources, Grafana bootstrap, security/login, and the desktop UI. Consolidate every active `*_revision.py` patch into its natural source module before deleting the patch loader. Package with PyInstaller `onedir`; keep Grafana external with existing/native/Docker-supported integration; separate replaceable `app/` payload from persistent `config/`, `runtime/`, `archives/`, and `reports/`.

**Tech Stack:** Python 3.12, PySide6, FastAPI, Uvicorn, MariaDB Connector/Python, SQLite, Selenium, ReportLab, pyqtgraph, PyInstaller, pytest, GitHub Actions, Grafana external/native/Docker integration.

**Spec:** `docs/superpowers/specs/2026-09-12-radmon-production-release-cleanup-design.md`

## Global Constraints

- Production target remains the central Windows PC at `192.168.1.2`.
- Windows release format is x64 PyInstaller `onedir`.
- Grafana remains external; do not bundle Grafana binaries.
- No source MariaDB schema migrations/DDL are introduced by this work.
- Existing configured production `source_id` values must remain stable.
- Persistent central runtime/security/archive/report data must survive restart and application replacement.
- Alarm Policy, response/ACK, suppression, write-through retry, archive, report, source health, Grafana projection, and WhatsApp behavior must remain functionally equivalent unless explicitly covered by an approved change.
- `RadMon.exe` must only stop resources it owns or can positively identify as stale RadMon components; it must never kill an unrelated process merely because port 8090 is occupied.
- Final production workflow must not require `.bat`, a Python interpreter, `.venv`, `pip`, `pytest`, `main.py`, or `central_server.py`.
- Historical dated design/implementation-plan documents are removed before final merge.
- The spec and this plan are temporary branch artifacts and are also removed before final merge to `main`.
- New behavior and bug fixes use TDD: failing test first, minimal implementation, green verification, then refactor.

---

## File Structure Map

### New focused modules

- `radmon/paths.py` — one source of truth for development and packaged installation paths.
- `radmon/central_service.py` — managed start/stop lifecycle for FastAPI/Uvicorn, LAN runtime, archive service, secure routes, and optional WhatsApp dispatcher.
- `radmon/production_app.py` — top-level central production orchestration and desktop lifecycle.
- `radmon/__main__.py` — source/package executable entry point calling `production_app.main()`.
- `packaging/RadMon.spec` — PyInstaller `onedir` build definition and runtime data inclusion.
- `scripts/build_release.py` — deterministic Windows release assembly/layout checks/ZIP creation.
- `requirements-dev.txt` — build/test-only dependencies such as pytest, PyInstaller, and CI helpers.
- `.github/workflows/windows-release.yml` — Windows packaged build/smoke/artifact workflow.

### Existing modules expected to absorb revision patches

- `radmon/repository.py`
- `radmon/lan.py`
- `radmon/lan_runtime.py`
- `radmon/remote_alarm.py`
- `radmon/archive_store.py`
- `radmon/archive_reports.py`
- `radmon/grafana_tv.py`
- `radmon/grafana_bootstrap.py`
- `radmon/alarm_policy.py`
- `radmon/alarm_policy_store.py`
- `radmon/secure_services.py` / `radmon/security.py` / `radmon/secure_context.py` as required by current patch behavior
- `radmon/admin/icons.py`
- `radmon/admin/main_window.py` and related UI modules where production integration patches currently attach behavior

### Transitional files to remove once replacements pass

- `RADMON.bat`
- `RUN_DUMMY.bat`
- `RUN_LAN.bat`
- `main.py`
- `central_server.py`
- all `radmon/*_revision.py`
- historical dated `docs/*design*.md` and `docs/*implementation-plan*.md`
- obsolete launcher-only tests
- zero-reference legacy icon assets
- `scripts/smoke_demo.py` if final reference analysis still shows no consumer

---

### Task 1: Introduce packaged/development path resolution

**Files:**
- Create: `radmon/paths.py`
- Create: `tests/test_paths.py`
- Modify: `radmon/config.py`

**Interfaces:**
- Produces: `ApplicationPaths` dataclass with `app_dir`, `config_dir`, `runtime_dir`, `archives_dir`, `reports_dir`, `assets_dir`, `grafana_dir`.
- Produces: `resolve_application_paths(executable: Path | None = None, frozen: bool | None = None) -> ApplicationPaths`.
- Produces: `production_env_path(paths: ApplicationPaths) -> Path`.
- Later tasks consume these paths instead of relying on current working directory.

- [ ] **Step 1: Write failing tests for development and packaged layouts**

```python
from pathlib import Path

from radmon.paths import resolve_application_paths


def test_source_layout_uses_repo_root(tmp_path, monkeypatch):
    fake_repo = tmp_path / "repo"
    (fake_repo / "radmon").mkdir(parents=True)
    paths = resolve_application_paths(executable=fake_repo / "python.exe", frozen=False)
    assert paths.app_dir == fake_repo
    assert paths.config_dir == fake_repo
    assert paths.runtime_dir == fake_repo / "runtime"


def test_packaged_layout_separates_app_and_persistent_data(tmp_path):
    root = tmp_path / "RadMon"
    exe = root / "app" / "RadMon.exe"
    exe.parent.mkdir(parents=True)
    paths = resolve_application_paths(executable=exe, frozen=True)
    assert paths.app_dir == root / "app"
    assert paths.config_dir == root / "config"
    assert paths.runtime_dir == root / "runtime"
    assert paths.archives_dir == root / "archives"
    assert paths.reports_dir == root / "reports"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/test_paths.py`
Expected: FAIL because `radmon.paths` does not exist.

- [ ] **Step 3: Implement `ApplicationPaths` and resolver**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class ApplicationPaths:
    app_dir: Path
    config_dir: Path
    runtime_dir: Path
    archives_dir: Path
    reports_dir: Path
    assets_dir: Path
    grafana_dir: Path


def resolve_application_paths(*, executable: Path | None = None, frozen: bool | None = None) -> ApplicationPaths:
    exe = Path(executable or sys.executable).resolve()
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        app_dir = exe.parent
        root = app_dir.parent
        return ApplicationPaths(
            app_dir=app_dir,
            config_dir=root / "config",
            runtime_dir=root / "runtime",
            archives_dir=root / "archives",
            reports_dir=root / "reports",
            assets_dir=app_dir / "assets",
            grafana_dir=app_dir / "grafana",
        )
    app_dir = Path(__file__).resolve().parents[1]
    return ApplicationPaths(
        app_dir=app_dir,
        config_dir=app_dir,
        runtime_dir=app_dir / "runtime",
        archives_dir=app_dir / "archives",
        reports_dir=app_dir / "reports",
        assets_dir=app_dir,
        grafana_dir=app_dir / "grafana",
    )


def production_env_path(paths: ApplicationPaths) -> Path:
    return paths.config_dir / ".env" if paths.config_dir != paths.app_dir else paths.app_dir / ".env"
```

- [ ] **Step 4: Wire `Settings.from_env()` to accept/derive the explicit env path without changing environment-variable semantics**

Add an optional `env_path: str | Path | None = None` argument and load that file explicitly before reading values. Preserve existing tests and behavior when omitted.

- [ ] **Step 5: Run targeted tests**

Run: `pytest -q tests/test_paths.py tests/test_archive_config.py tests/test_production_integration_fix.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/paths.py radmon/config.py tests/test_paths.py
git commit -m "feat: add production-safe application paths"
```

---

### Task 2: Extract central service into a managed start/stop component

**Files:**
- Create: `radmon/central_service.py`
- Create: `tests/test_central_service.py`
- Modify: `central_server.py` temporarily to delegate to the new component

**Interfaces:**
- Produces: `CentralService(settings: Settings, host: str = "0.0.0.0", port: int = 8090)`.
- Produces: `start() -> None`, `wait_ready(timeout: float = 30.0) -> None`, `stop(timeout: float = 10.0) -> None`, `is_running -> bool`.
- Must preserve current `central_server.py` assembly of archive, security, policy reconciliation, secure routes, optional WhatsApp dispatcher, and `LanRuntime`.

- [ ] **Step 1: Write failing lifecycle tests using a minimal test app/service seam**

```python

def test_central_service_stop_is_idempotent(service):
    service.start()
    service.stop()
    service.stop()
    assert not service.is_running


def test_central_service_releases_listening_socket(service):
    service.start()
    service.wait_ready(timeout=5)
    assert service.is_running
    service.stop()
    assert not service.is_running
```

Use dependency injection for the Uvicorn server factory in tests so these tests do not require production MariaDB.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_central_service.py`
Expected: FAIL because managed service does not exist.

- [ ] **Step 3: Refactor current `central_server.py` setup into `CentralService`**

Implement a managed Uvicorn `Server` in a background thread. Preserve the current setup order: schema validation, secure services, runtime projection schema, policy restore/reconcile, archive catalog/reconcile, optional quarter archive service, API construction, secure route attachment, optional WhatsApp dispatcher, LAN runtime start.

`stop()` must request Uvicorn shutdown, stop LAN runtime in `finally`, join the thread with timeout, and be safe when called repeatedly.

- [ ] **Step 4: Make `central_server.py` a temporary thin wrapper**

It should parse host/port, construct `Settings.from_env()`, create `CentralService`, start, block until stopped/KeyboardInterrupt, then stop in `finally`.

- [ ] **Step 5: Run central/API regression tests**

Run: `pytest -q tests/test_central_service.py tests/test_central_archive_wiring.py tests/test_central_repository.py tests/test_secure_api.py tests/test_lan_ownership.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/central_service.py central_server.py tests/test_central_service.py
git commit -m "refactor: manage central service lifecycle in-process"
```

---

### Task 3: Add a production application supervisor and single executable source entry point

**Files:**
- Create: `radmon/production_app.py`
- Create: `radmon/__main__.py`
- Create: `tests/test_production_app.py`
- Modify: `main.py` temporarily to delegate to the supervisor where practical
- Modify: `radmon/single_instance.py` only if ownership metadata is needed

**Interfaces:**
- Produces: `ProductionApplication` with `run() -> int` and `shutdown() -> None`.
- Produces: `production_app.main() -> int`.
- Consumes: `ApplicationPaths`, `CentralService`, existing security/login/UI services, Grafana bootstrap, `SingleInstanceLock`.

- [ ] **Step 1: Write failing orchestration tests with injected factories**

```python

def test_ui_exit_stops_central_before_process_returns(fake_app):
    result = fake_app.run()
    assert result == 0
    assert fake_app.events == ["central-start", "ui-run", "central-stop", "lock-release"]


def test_startup_failure_after_central_start_still_stops_central(fake_app_with_ui_failure):
    assert fake_app_with_ui_failure.run() != 0
    assert "central-stop" in fake_app_with_ui_failure.events
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_production_app.py`
Expected: FAIL because `ProductionApplication` does not exist.

- [ ] **Step 3: Implement supervisor with explicit `try/finally` ownership**

`run()` must resolve paths, load settings from the production env path, acquire single-instance lock, initialize/validate database and security, start `CentralService`, wait for health, prepare Grafana integration, create/login/bootstrap admin UI, show the main window, block on `QApplication.exec()`, then stop owned central resources and release lock in `finally`.

- [ ] **Step 4: Add `radmon/__main__.py`**

```python
from radmon.production_app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Preserve developer testability**

Keep dependency-injection seams for central service factory, GUI factory, and Grafana bootstrap so lifecycle tests remain independent of live source MariaDB and GUI display.

- [ ] **Step 6: Run targeted regression tests**

Run: `pytest -q tests/test_production_app.py tests/test_admin_startup_smoke.py tests/test_security.py tests/test_qt_smoke.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/production_app.py radmon/__main__.py main.py radmon/single_instance.py tests/test_production_app.py
git commit -m "feat: add single production application supervisor"
```

---

### Task 4: Implement safe stale-RadMon detection without killing unrelated port owners

**Files:**
- Modify: `radmon/production_app.py`
- Create: `radmon/process_ownership.py`
- Create: `tests/test_process_ownership.py`

**Interfaces:**
- Produces: `PortOwner(pid: int, command_line: str, executable: str | None)`.
- Produces: `find_listening_owner(port: int) -> PortOwner | None` on Windows.
- Produces: `is_stale_radmon_central(owner: PortOwner) -> bool`.
- Produces: `stop_stale_radmon(owner: PortOwner) -> None` only after positive identification.

- [ ] **Step 1: Write failing classification tests**

```python

def test_identifies_legacy_central_server_as_radmon():
    owner = PortOwner(123, r"python.exe C:\RadMon\central_server.py --port 8090", "python.exe")
    assert is_stale_radmon_central(owner)


def test_does_not_identify_unrelated_python_process():
    owner = PortOwner(456, r"python.exe other_service.py --port 8090", "python.exe")
    assert not is_stale_radmon_central(owner)
```

Also cover packaged `RadMon.exe` metadata if a future stale process can be positively distinguished from the active instance.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_process_ownership.py`
Expected: FAIL.

- [ ] **Step 3: Implement Windows ownership inspection**

Use `Get-NetTCPConnection`/CIM through a narrowly scoped subprocess or `psutil` only if explicitly added and justified. Prefer no new runtime dependency if native Windows PowerShell/CIM can provide PID + command line robustly.

- [ ] **Step 4: Integrate startup guard**

If port 8090 is occupied by an unrelated process, raise a user-visible startup error and do not terminate it. If it is positively identified as stale legacy RadMon central, stop it and verify the port is released before central startup.

- [ ] **Step 5: Run tests**

Run: `pytest -q tests/test_process_ownership.py tests/test_production_app.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/process_ownership.py radmon/production_app.py tests/test_process_ownership.py
git commit -m "fix: recover only positively identified stale RadMon processes"
```

---

### Task 5: Consolidate repository/LAN/remote-alarm revision patches

**Files:**
- Modify: `radmon/repository.py`
- Modify: `radmon/lan.py`
- Modify: `radmon/lan_runtime.py`
- Modify: `radmon/remote_alarm.py`
- Modify: existing LAN/repository/alarm tests as required for direct behavior imports
- Delete after parity: `radmon/repository_revision.py`, `radmon/lan_revision.py`, `radmon/remote_alarm_revision.py`
- Modify: `radmon/__init__.py`

**Interfaces:**
- Preserve public classes/functions currently exposed after patch application.
- No consumer may require importing `radmon` solely to mutate another module at runtime.

- [ ] **Step 1: Inventory exact monkey-patched symbols from the three revision modules and add direct-import parity assertions**

For each patched method/function, add a regression test that imports the final target module directly and asserts the behavior currently supplied by the revision patch.

- [ ] **Step 2: Temporarily disable one patch at a time in a local worktree and verify the new parity test fails**

Run the smallest test file that demonstrates the missing behavior. Expected: FAIL for the reason provided by the removed patch.

- [ ] **Step 3: Move repository patch behavior into `repository.py`**

Keep exact SQL/source-safety behavior, especially legacy source schema compatibility and stable source IDs.

- [ ] **Step 4: Run repository tests**

Run: `pytest -q tests/test_repository_contract.py tests/test_legacy_schema_runtime.py tests/test_station_catalog.py tests/test_vrecent_contract.py`
Expected: PASS without `repository_revision.apply()`.

- [ ] **Step 5: Move LAN patch behavior into `lan.py`/`lan_runtime.py`**

Preserve checkpointing, backfill, ownership, polling, source health, policy dispatch, and retry semantics.

- [ ] **Step 6: Run LAN tests**

Run: `pytest -q tests/test_lan.py tests/test_lan_archive.py tests/test_lan_ownership.py tests/test_source_health.py tests/test_runtime_status_projection.py`
Expected: PASS without `lan_revision.apply()`.

- [ ] **Step 7: Move remote alarm patch behavior into `remote_alarm.py`**

- [ ] **Step 8: Run remote alarm tests**

Run: `pytest -q tests/test_remote_alarm.py tests/test_alarm_policy_integration.py`
Expected: PASS without `remote_alarm_revision.apply()`.

- [ ] **Step 9: Remove three revision imports from `radmon/__init__.py`, delete the revision files, and rerun all targeted tests**

- [ ] **Step 10: Commit**

```bash
git add radmon tests
git commit -m "refactor: fold repository and LAN revisions into source"
```

---

### Task 6: Consolidate archive revision patches

**Files:**
- Modify: `radmon/archive_store.py`
- Modify: `radmon/archive_reports.py`
- Delete: `radmon/archive_store_revision.py`
- Delete: `radmon/archive_reports_revision.py`
- Modify: `radmon/__init__.py`
- Test: existing archive test suite

**Interfaces:**
- Preserve archive reconciliation, quarter boundaries, corruption handling, report lookup, bundle behavior, and active/archive composite report semantics.

- [ ] **Step 1: Add/strengthen direct-import parity tests for patched archive behavior**
- [ ] **Step 2: Verify RED when each archive revision patch is disabled**
- [ ] **Step 3: Fold store behavior into `archive_store.py`**
- [ ] **Step 4: Fold report behavior into `archive_reports.py`**
- [ ] **Step 5: Remove patch imports and revision files**
- [ ] **Step 6: Run archive suite**

Run: `pytest -q tests/test_archive.py tests/test_archive_api.py tests/test_archive_bundle_config.py tests/test_archive_config.py tests/test_archive_corruption.py tests/test_archive_reconcile_reports.py tests/test_archive_report_boundaries.py tests/test_archive_reports.py tests/test_archive_reports_ui.py tests/test_central_archive_wiring.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon tests
git commit -m "refactor: fold archive revisions into source"
```

---

### Task 7: Consolidate alarm-policy revision patches

**Files:**
- Modify: `radmon/alarm_policy.py`
- Modify: `radmon/alarm_policy_store.py`
- Modify: `radmon/secure_services.py`
- Modify: `radmon/secure_context.py` / `radmon/security.py` only where the existing security revision actually applies behavior
- Modify: `radmon/lan_runtime.py` if runtime patch behavior belongs there
- Delete: `radmon/alarm_policy_revision.py`
- Delete: `radmon/alarm_policy_store_revision.py`
- Delete: `radmon/alarm_policy_security_revision.py`
- Delete: `radmon/alarm_policy_runtime_revision.py`
- Modify: `radmon/__init__.py`

**Interfaces:**
- Preserve max-three alarms per five-minute window anchored at alarm #1.
- Preserve retrigger lock after #3.
- Only true NORMAL below warning threshold resets lock/counter; ALERT does not.
- Preserve suppression 1 minute–24 hours, PIN/PIC/reason authorization, optional NORMAL auto-resume, one SUPPRESSED event per session, dose visibility, write-through retry, restart safety, and WhatsApp gating/idempotence.

- [ ] **Step 1: Ensure existing policy tests directly import final modules and lock all approved semantics**
- [ ] **Step 2: Disable each policy revision patch one at a time and verify a corresponding test fails**
- [ ] **Step 3: Fold core policy behavior into `alarm_policy.py`**
- [ ] **Step 4: Fold store transaction/readback behavior into `alarm_policy_store.py`**
- [ ] **Step 5: Fold security/runtime integration into their natural modules**
- [ ] **Step 6: Remove revision imports/files**
- [ ] **Step 7: Run policy suite**

Run: `pytest -q tests/test_alarm_policy.py tests/test_alarm_policy_api.py tests/test_alarm_policy_integration.py tests/test_alarm_policy_notifications.py tests/test_alarm_policy_resilience.py tests/test_alarm_policy_snapshot.py tests/test_alarm_policy_source_retry.py tests/test_alarm_policy_store.py tests/test_alarm_suppression.py tests/test_alarm_suppression_ui.py tests/test_whatsapp.py`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add radmon tests
git commit -m "refactor: fold alarm policy revisions into source"
```

---

### Task 8: Consolidate Grafana and production integration revisions

**Files:**
- Modify: `radmon/grafana_bootstrap.py`
- Modify: `radmon/grafana_tv.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/admin/icons.py`
- Modify: other direct UI/domain modules only where existing production patches attach behavior
- Delete after parity:
  - `radmon/grafana_revision.py`
  - `radmon/grafana_bootstrap_revision.py`
  - `radmon/grafana_wib_revision.py`
  - `radmon/grafana_policy_revision.py`
  - `radmon/production_integration_revision.py`
  - `radmon/production_integration_compat_revision.py`
  - `radmon/production_safety_revision.py`
  - `radmon/icon_system_revision.py`
- Modify: `radmon/__init__.py`

**Interfaces:**
- Preserve external Grafana reuse/native/Docker fallback behavior.
- Preserve WIB wall-clock conversion, policy JOIN projection, dashboard/playlist generation, direct monitoring launch, semantic icon registry, manual links, station/source grouping, and production safety guards.

- [ ] **Step 1: Add direct parity tests for every monkey-patched production/Grafana/UI symbol not already directly covered**
- [ ] **Step 2: Verify RED by disabling one patch at a time**
- [ ] **Step 3: Fold Grafana payload/query behavior into `grafana_tv.py`**
- [ ] **Step 4: Fold bootstrap/reprovision behavior into `grafana_bootstrap.py`**
- [ ] **Step 5: Fold UI/production integration into direct UI/domain modules**
- [ ] **Step 6: Fold icon behavior into `admin/icons.py` and direct call sites**
- [ ] **Step 7: Remove all eight revision imports/files**
- [ ] **Step 8: Simplify `radmon/__init__.py` to metadata/package declarations only**

Expected final shape:

```python
"""Python-first radiation monitoring components for DPFK."""

__version__ = "0.1.0"
```

- [ ] **Step 9: Run Grafana/UI/production regression suite**

Run: `pytest -q tests/test_grafana_alarm_policy.py tests/test_grafana_bootstrap_fast_open.py tests/test_grafana_bootstrap_playlist.py tests/test_grafana_monitoring.py tests/test_grafana_reprovision.py tests/test_grafana_revision.py tests/test_grafana_tv.py tests/test_grafana_tv_visibility.py tests/test_grafana_wib_time.py tests/test_monitoring_chart_direct_main.py tests/test_production_integration_fix.py tests/test_production_safety_guards.py tests/test_production_source_safety.py tests/test_icon_registry.py tests/test_legacy_ui_parity.py`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add radmon tests
git commit -m "refactor: remove runtime revision patch layer"
```

---

### Task 9: Remove `.bat` launchers and replace launcher tests with supervisor tests

**Files:**
- Delete: `RADMON.bat`
- Delete: `RUN_DUMMY.bat`
- Delete: `RUN_LAN.bat`
- Delete or rewrite: `tests/test_run_lan_launcher.py`
- Delete or rewrite: `tests/test_windows_launchers.py`
- Modify: `tests/test_windows_launcher_timezone.py`
- Modify: `tests/test_runtime_v2.py`
- Modify: `tests/test_launchers_v3.py`
- Modify: `tests/test_lan_ownership.py` where it asserts launcher text

**Interfaces:**
- Old launcher text/content is no longer part of the product contract.
- Equivalent lifecycle requirements must be asserted through `ProductionApplication`, `CentralService`, paths, and packaged release layout.

- [ ] **Step 1: Write replacement tests that assert there are no root `.bat` files and the production entry point exists in source**

```python

def test_no_batch_launchers_remain():
    assert list(ROOT.glob("*.bat")) == []


def test_production_entry_point_is_module_based():
    assert (ROOT / "radmon" / "__main__.py").is_file()
    assert (ROOT / "radmon" / "production_app.py").is_file()
```

- [ ] **Step 2: Run tests before deletion and verify RED**
- [ ] **Step 3: Delete `.bat` files and obsolete text-structure tests**
- [ ] **Step 4: Rewrite timezone dependency test to assert `tzdata` is in runtime requirements, not duplicated bootstrap commands**
- [ ] **Step 5: Run launcher replacement tests plus lifecycle tests**

Run: `pytest -q tests/test_production_app.py tests/test_central_service.py tests/test_process_ownership.py tests/test_runtime_v2.py tests/test_windows_launcher_timezone.py tests/test_launchers_v3.py tests/test_lan_ownership.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "cleanup: remove obsolete batch launchers"
```

---

### Task 10: Add PyInstaller onedir packaging and release assembly

**Files:**
- Create: `packaging/RadMon.spec`
- Create: `scripts/build_release.py`
- Create: `requirements-dev.txt`
- Modify: `requirements.txt`
- Create: `tests/test_release_layout.py`
- Modify: `.gitignore`

**Interfaces:**
- `python scripts/build_release.py --output dist-release` builds/assembles a versioned release directory and ZIP on Windows.
- Release app payload contains `RadMon.exe`, `_internal/`, `.env.example`, required assets/manuals/Grafana resources.
- Production `.env` is never copied into the artifact.

- [ ] **Step 1: Split build/test dependencies from runtime dependencies**

Move `pytest>=8,<10` out of `requirements.txt` into `requirements-dev.txt`. Add compatible PyInstaller and CI-only helpers there. Keep runtime libraries required by the packaged app in `requirements.txt`.

- [ ] **Step 2: Write failing release-layout tests against an assembled fixture tree**

```python

def test_release_contains_single_operator_entry_point(release_root):
    assert (release_root / "app" / "RadMon.exe").is_file()
    assert not list(release_root.rglob("*.bat"))
    assert not (release_root / "app" / ".env").exists()
    assert (release_root / "app" / ".env.example").is_file()
```

Also assert source `.py`, tests, and dated engineering docs are absent from the distribution.

- [ ] **Step 3: Run RED**

Run: `pytest -q tests/test_release_layout.py`
Expected: FAIL because packaging assembler does not exist.

- [ ] **Step 4: Create `packaging/RadMon.spec`**

Set entry script to `radmon/__main__.py`, `name="RadMon"`, `console=False`, and include only required runtime data files: active icons/assets, runtime HTML manuals, `.env.example`, and Grafana resources still used by bootstrap.

- [ ] **Step 5: Implement `scripts/build_release.py`**

Required behavior: clean prior build output; run PyInstaller; create `RadMon-<version>/app`; copy PyInstaller onedir payload; copy `.env.example`; create empty/preserved-layout directories only in installation guidance, not as destructive replacements; validate forbidden files; create `RadMon-<version>-windows-x64.zip`.

- [ ] **Step 6: Run release-layout tests**

Run: `pytest -q tests/test_release_layout.py`
Expected: PASS against fixture/assembler validation helpers.

- [ ] **Step 7: On Windows, build the executable**

Run: `python scripts/build_release.py --output dist-release`
Expected: `dist-release/RadMon-<version>/app/RadMon.exe` and ZIP artifact.

- [ ] **Step 8: Commit**

```bash
git add packaging scripts/build_release.py requirements.txt requirements-dev.txt tests/test_release_layout.py .gitignore
git commit -m "build: add Windows RadMon executable release"
```

---

### Task 11: Add deterministic packaged smoke/diagnostic mode

**Files:**
- Modify: `radmon/production_app.py`
- Modify: `radmon/__main__.py`
- Create: `tests/test_packaged_smoke.py`
- Modify: `packaging/RadMon.spec` only if extra runtime data is discovered

**Interfaces:**
- Provide a non-production diagnostic invocation such as `RadMon.exe --smoke-test` used only by CI/build verification.
- Smoke mode must not connect to live detector/source MariaDB hosts or require interactive login.
- It must exercise packaged imports, path resolution, resource discovery, configuration parser construction, and managed central service start/stop through test doubles or a local minimal app seam.

- [ ] **Step 1: Write failing CLI smoke test**

```python

def test_smoke_mode_exits_zero_without_live_sources(monkeypatch):
    monkeypatch.setattr("sys.argv", ["RadMon.exe", "--smoke-test"])
    assert main() == 0
```

- [ ] **Step 2: Run RED**
- [ ] **Step 3: Implement argument parsing and isolated smoke path**
- [ ] **Step 4: Run source smoke test**

Run: `pytest -q tests/test_packaged_smoke.py`
Expected: PASS.

- [ ] **Step 5: Run packaged smoke on Windows**

Run: `dist-release\RadMon-<version>\app\RadMon.exe --smoke-test`
Expected: exit code 0 and no orphan process/listener.

- [ ] **Step 6: Commit**

```bash
git add radmon/production_app.py radmon/__main__.py tests/test_packaged_smoke.py packaging/RadMon.spec
git commit -m "test: add packaged application smoke mode"
```

---

### Task 12: Add Windows release CI

**Files:**
- Create: `.github/workflows/windows-release.yml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Linux/source CI continues to run pytest + compile + Grafana payload validation.
- Windows workflow installs runtime + dev requirements, builds PyInstaller onedir, runs packaged smoke, validates release layout, and uploads ZIP artifact.

- [ ] **Step 1: Update source CI compile command to compile package modules rather than deleted top-level launchers**

Replace `python -m compileall -q main.py central_server.py radmon` with `python -m compileall -q radmon scripts`.

- [ ] **Step 2: Update source CI dependency install**

Install `requirements.txt` and `requirements-dev.txt`.

- [ ] **Step 3: Create Windows workflow**

Core steps:

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- run: python -m pip install -r requirements.txt -r requirements-dev.txt
- run: python scripts/build_release.py --output dist-release
- run: python -m pytest -q tests/test_release_layout.py tests/test_packaged_smoke.py
- run: dist-release\...\app\RadMon.exe --smoke-test
- uses: actions/upload-artifact@v4
```

Resolve the exact versioned artifact path in PowerShell from the build output instead of hard-coding a version string.

- [ ] **Step 4: Validate workflow syntax locally with YAML parser if available**
- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/windows-release.yml
git commit -m "ci: build and smoke-test Windows RadMon release"
```

---

### Task 13: Remove top-level Python launchers after package entry point is proven

**Files:**
- Delete: `main.py`
- Delete: `central_server.py`
- Modify tests/docs that still reference them
- Modify `.github/workflows/ci.yml` if any reference remains

**Interfaces:**
- Source developer execution becomes `python -m radmon`.
- Production execution remains `RadMon.exe`.

- [ ] **Step 1: Search repository for `main.py` and `central_server.py` references and classify each**
- [ ] **Step 2: Add test asserting deprecated top-level launchers are absent**
- [ ] **Step 3: Verify RED while files still exist**
- [ ] **Step 4: Delete files and update legitimate references**
- [ ] **Step 5: Run entry/lifecycle/source smoke tests**

Run: `pytest -q tests/test_production_app.py tests/test_central_service.py tests/test_packaged_smoke.py tests/test_release_layout.py`
Expected: PASS.

- [ ] **Step 6: Run `python -m radmon --smoke-test`**
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "cleanup: remove legacy Python entry points"
```

---

### Task 14: Remove dead icons, scripts, duplicated resources, and historical docs

**Files:**
- Delete proven-unused assets under `radmon/admin/icons/silk/`
- Delete unused Tabler icons not referenced by `radmon/admin/icons.py` or direct runtime assets
- Delete `scripts/smoke_demo.py` if no final consumer
- Delete historical dated design/implementation-plan docs under `docs/`
- Keep/update: `README.md`, `docs/INSTALLATION.md`, `docs/USER-MANUAL.md`, runtime HTML manuals if still opened by UI
- Test: `tests/test_icon_registry.py`, production integration/manual tests, release-layout tests

**Interfaces:**
- Semantic icon registry remains the only UI icon access path.
- Runtime manuals remain available if current UI still opens them.

- [ ] **Step 1: Generate an explicit asset/reference inventory**

Search all code/tests/packaging config for each icon/resource basename. Mark files as ACTIVE or ZERO-REFERENCE. Do not delete by folder name alone.

- [ ] **Step 2: Add a test that every icon registry target exists and every shipped icon is referenced by the registry unless explicitly documented as a packaging resource**
- [ ] **Step 3: Delete zero-reference Silk and Tabler assets**
- [ ] **Step 4: Search for `scripts/smoke_demo.py`; delete only if still zero-reference**
- [ ] **Step 5: Delete historical dated design/implementation-plan docs already approved for removal**
- [ ] **Step 6: Run UI/manual/resource tests**

Run: `pytest -q tests/test_icon_registry.py tests/test_production_integration_fix.py tests/test_release_layout.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "cleanup: remove dead assets scripts and historical docs"
```

---

### Task 15: Rewrite current documentation for executable-based production deployment

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTALLATION.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/manual/installation.html`
- Modify: `docs/manual/user-manual.html`

**Interfaces:**
- Production SOP must describe `RadMon.exe`, external Grafana expectations, persistent-data layout, upgrade, rollback, shutdown verification, and diagnostics.
- Remove production instructions for `.bat`, `.venv`, `pip install`, `pytest`, `git pull` as the normal deployment mechanism.

- [ ] **Step 1: Add documentation assertions where existing tests validate manual paths/content**
- [ ] **Step 2: Rewrite installation docs around `C:\RadMon\app`, `config`, `runtime`, `archives`, `reports`, `backup`**
- [ ] **Step 3: Document external Grafana behavior and prerequisite clearly**
- [ ] **Step 4: Document update and rollback procedure**
- [ ] **Step 5: Run manual/product integration tests**

Run: `pytest -q tests/test_production_integration_fix.py tests/test_release_layout.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md docs
git commit -m "docs: document executable production deployment"
```

---

### Task 16: Full regression, release verification, and cleanup of temporary spec/plan

**Files:**
- Potential fixes only where verification exposes real regressions
- Delete before final merge:
  - `docs/superpowers/specs/2026-09-12-radmon-production-release-cleanup-design.md`
  - `docs/superpowers/plans/2026-09-12-radmon-production-release-cleanup.md`

**Interfaces:**
- No success claim until all required verification evidence is fresh.

- [ ] **Step 1: Run full source test suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: all tests pass, zero failures.

- [ ] **Step 2: Compile package and scripts**

Run: `python -m compileall -q radmon scripts`
Expected: exit 0.

- [ ] **Step 3: Validate Grafana payloads using the CI validation block**
Expected: dashboard/playlist payload validation passes.

- [ ] **Step 4: Build Windows release in CI or a Windows checkout**

Run: `python scripts/build_release.py --output dist-release`
Expected: valid `RadMon-<version>-windows-x64.zip`.

- [ ] **Step 5: Run packaged smoke**

Run: `RadMon.exe --smoke-test`
Expected: exit 0, no orphan RadMon process, no listener left on 8090.

- [ ] **Step 6: Inspect final repository for forbidden leftovers**

Required checks:

```text
no root *.bat
no radmon/*_revision.py
no top-level main.py
no top-level central_server.py
no historical dated design/implementation-plan docs
no zero-reference asset set retained without reason
```

- [ ] **Step 7: Verify source MariaDB safety tests explicitly**

Run: `pytest -q tests/test_production_source_safety.py tests/test_legacy_schema_runtime.py`
Expected: PASS.

- [ ] **Step 8: Remove the temporary cleanup design spec and implementation plan from `release-cleanup`**

This is intentional and required by the approved cleanup design.

- [ ] **Step 9: Rerun full suite after deleting the temporary docs**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: all tests pass.

- [ ] **Step 10: Commit final cleanup**

```bash
git add -A
git commit -m "cleanup: finalize production executable release"
```

- [ ] **Step 11: Confirm GitHub Actions source CI and Windows release workflow are both successful on the final branch head**

Do not merge or call the release production-ready until both are green.

- [ ] **Step 12: Physical production commissioning checklist after merge/release**

On the central PC: preserve `config/.env`, `runtime/`, `archives/`, `reports/`; install/replace only `app/`; launch `RadMon.exe`; verify central `/health`; verify `.50/.52/.38` reachability using unchanged production source IDs; verify Grafana dashboards; verify one real alarm/response/suppression flow under controlled conditions; close RadMon and confirm port 8090 is free; relaunch and confirm no duplicate notification/state regression.
