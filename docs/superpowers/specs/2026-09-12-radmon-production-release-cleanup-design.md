# RadMon Production Release Cleanup Design

Date: 2026-09-12
Branch: `release-cleanup`
Base: `main` at `f12b0b66e13a3c06be0678bb65d17517116089e0`

## 1. Purpose

RadMon production must stop behaving like a developer checkout. The production operator should start the complete central-PC application by launching one ready-to-use Windows executable, and closing that application must stop every RadMon-owned service cleanly.

This work also removes accumulated compatibility layers, dead launchers, historical engineering documents, unused resources, and duplicate code after proving that their active behavior has been preserved in the final modules.

The target is the central production PC at `192.168.1.2`. The production release is Windows x64 and uses a PyInstaller `onedir` build. Grafana remains an external dependency rather than being bundled into the RadMon release.

## 2. User-visible contract

The production operator has one entry point:

```text
RadMon.exe
```

Starting `RadMon.exe` starts the RadMon central stack and opens the desktop Admin UI. Closing the desktop UI shuts down the RadMon-owned central API, LAN collector, WhatsApp dispatcher resources, and other RadMon-owned background resources before the executable exits.

The operator must not need to run `.bat` files, `python`, `pip`, `pytest`, `main.py`, or `central_server.py`.

A normal production update becomes:

1. Close RadMon.
2. Confirm the previous RadMon process has exited.
3. Back up persistent state.
4. Replace the versioned application payload with the new release payload.
5. Preserve production configuration and persistent data.
6. Launch `RadMon.exe`.

## 3. Scope

### In scope

- One production executable entry point for the central PC.
- Central API and LAN collector lifecycle owned by the application supervisor.
- Clean shutdown with no orphan central process on port 8090.
- PyInstaller `onedir` Windows x64 release.
- Stable runtime/resource path resolution for packaged and development execution.
- External Grafana discovery/provisioning and supported Docker fallback.
- Consolidation of all active `*_revision.py` monkey patches into final source modules.
- Removal of obsolete `.bat` launchers.
- Removal of historical design/implementation-plan documents.
- Removal of dead scripts, resources, compatibility code, and duplicated tests after proof of non-use or replacement.
- CI coverage for source tests and Windows packaged-release build/smoke validation.
- Production-safe upgrade and rollback layout.

### Out of scope

- Bundling Grafana binaries into RadMon.
- Building an internet auto-updater.
- Changing the source MariaDB schema on detector/source machines.
- Changing the alarm policy functional requirements already implemented.
- Replacing MariaDB, Grafana, Selenium WhatsApp, PySide6, or FastAPI as technologies.
- Destructive migration of existing central SQLite state.

## 4. Safety invariants

The refactor must preserve these production invariants:

- Legacy source MariaDB databases remain schema-compatible and receive no new DDL/migrations from this project.
- Production source identities remain stable; existing configured `source_id` values must not be silently renamed.
- Central runtime/security state remains persistent across restart and release upgrades.
- Alarm Policy, ACK/response, suppression, retry/write-through, archive, report, source health, API, Grafana, and notification behavior remain functionally equivalent unless a separately approved change says otherwise.
- Suppression must not hide the measured dose value or rewrite historical source evidence.
- RadMon only stops processes/resources it owns or can positively identify as stale RadMon components. It must not kill an unrelated process merely because it uses a familiar port.

## 5. Target production architecture

### 5.1 Application supervisor

A production supervisor module becomes the single lifecycle owner. The packaged entry point calls this supervisor directly.

Conceptual responsibilities:

```text
RadMon.exe
  -> resolve installation paths
  -> load/validate production configuration
  -> acquire single-instance ownership
  -> inspect port 8090 and recover positively identified stale RadMon ownership
  -> initialize central services
  -> start Uvicorn/FastAPI under managed application ownership
  -> start LAN runtime/collector
  -> initialize optional WhatsApp dispatcher
  -> wait for central /health readiness
  -> discover/provision supported external Grafana
  -> start login/Admin desktop UI
  -> wait for UI exit
  -> stop LAN runtime and owned dispatchers
  -> stop Uvicorn/FastAPI
  -> release resources and single-instance ownership
  -> exit process
```

The preferred architecture is a single Windows process with the central server hosted as a managed background service/thread inside `RadMon.exe`. A second Python/EXE child process is not the default design because separate process ownership is the root of the current orphan-service failure mode.

### 5.2 Internal module boundaries

The implementation should create explicit modules with focused responsibilities. Exact names may be adjusted during implementation if existing module boundaries make a different name clearer, but the responsibilities remain fixed:

- `radmon/production_app.py`: top-level production lifecycle orchestration.
- `radmon/central_service.py`: start/stop interface around FastAPI/Uvicorn central service and LAN runtime ownership.
- `radmon/paths.py`: packaged/development application, config, runtime, archive, report, asset, and Grafana resource path resolution.
- Existing domain modules continue to own repository, alarm, archive, security, Grafana payload, and UI logic.

`main.py` and `central_server.py` are transitional entry points only. After packaged and source execution no longer require them, they are removed from the final source tree.

## 6. Shutdown and stale-process behavior

Closing the Admin UI is a full RadMon central shutdown request.

Required shutdown order:

1. Stop accepting new operator work.
2. Stop LAN collector/runtime cleanly.
3. Stop RadMon-owned WhatsApp/background dispatch resources.
4. Stop central FastAPI/Uvicorn service.
5. Flush/close owned database/runtime resources where applicable.
6. Release the single-instance lock.
7. Confirm the process can exit without leaving a listener on port 8090.

On startup, if port 8090 is occupied:

- If the occupant can be positively identified as a stale RadMon central process from a previous release, RadMon may recover/stop it safely before continuing.
- If the occupant is healthy RadMon owned by another active instance, startup must refuse the duplicate instance.
- If the occupant is not positively identified as RadMon, startup must abort with a clear message and must not kill it.

## 7. Grafana strategy

Grafana remains external by explicit user decision.

RadMon preserves support for:

- Reusing a healthy existing Grafana instance.
- Reprovisioning/updating the RadMon datasource, dashboards, and playlist on a healthy supported Grafana instance.
- Using the supported Docker Compose fallback where production configuration and environment support it.
- Using an installed native Grafana executable where supported by the current bootstrap behavior.

RadMon does not bundle Grafana binaries in the release and does not stop a pre-existing external Grafana instance when RadMon exits.

`grafana/docker-compose.yml` and provisioning resources are kept only if the final runtime path still uses them. They are not deleted merely because the production executable replaces the `.bat` launcher.

## 8. Release and installation layout

### 8.1 Build artifact

The Windows CI build produces a versioned ZIP containing an application payload built with PyInstaller `onedir`.

Conceptual artifact:

```text
RadMon-<version>-windows-x64.zip
  app/
    RadMon.exe
    _internal/
    assets/
    grafana/                 # only resources still required by bootstrap/provisioning
    .env.example
```

No production secrets are embedded in the artifact.

### 8.2 Installed production layout

The recommended installation root separates replaceable program files from persistent state:

```text
C:\RadMon\
  app\
    RadMon.exe
    _internal\
    assets\
    grafana\
    .env.example
  config\
    .env
  runtime\
  archives\
  reports\
  backup\
    app-previous\
```

The operator launches `C:\RadMon\app\RadMon.exe` directly or through a shortcut that targets that executable.

This separation makes upgrades deterministic: replace `app\`, preserve `config\`, `runtime\`, `archives\`, and `reports\`.

## 9. Configuration and path resolution

A single path-resolution API replaces assumptions that the process current working directory is the repository root.

The path layer must handle both:

- development/source execution from a checkout; and
- packaged PyInstaller execution from `app\RadMon.exe`.

Production `.env` is loaded from the persistent configuration location, not embedded inside the executable. `.env.example` is shipped only as a template.

Persistent resources must resolve outside the replaceable application payload:

- security/runtime SQLite database;
- runtime status/state files;
- archives;
- generated reports;
- logs and other durable runtime outputs.

Read-only packaged assets resolve from the application payload:

- icons still used by the UI;
- HTML manuals if retained as runtime help assets;
- Grafana provisioning/config templates still used by bootstrap.

## 10. Packaging strategy

PyInstaller `onedir` is the release format.

Reasons:

- PySide6 and native dependencies are more predictable than with a temporary `onefile` extraction model.
- MariaDB/native DLL diagnostics are easier.
- Startup is faster and less sensitive to antivirus/temp-directory behavior.
- The user still has exactly one executable entry point.

The repository gains explicit packaging configuration, for example:

```text
packaging/
  RadMon.spec
scripts/
  build_release.py
```

Build-only tooling is separated from runtime dependencies. `pytest` and PyInstaller belong to development/build requirements rather than the packaged runtime application dependency set.

## 11. Compatibility-patch consolidation

The current package imports and applies many `*_revision.py` modules from `radmon/__init__.py`. Those files are active behavior, not dead files, so they cannot be deleted first.

The cleanup uses the rule:

```text
consolidate -> prove parity -> delete patch
```

Active behavior from revision modules is moved into its natural final module. Examples include:

- repository revisions into repository/database modules;
- LAN revisions into LAN/runtime modules;
- remote alarm revisions into remote alarm modules;
- archive revisions into archive store/report modules;
- Grafana revisions into Grafana payload/bootstrap modules;
- alarm-policy revisions into alarm policy/store/security/runtime modules;
- production integration/safety revisions into final production/UI/domain modules;
- icon revision behavior into the semantic icon registry and its direct consumers.

After parity tests pass, the corresponding revision modules are deleted and `radmon/__init__.py` becomes a normal package initializer without runtime monkey-patching.

No `*_revision.py` file remains in the final intended architecture.

## 12. Cleanup rules

A file or code path is deleted only when all applicable checks are satisfied:

1. No remaining import/reference from active code or tests that represent current behavior.
2. No runtime resource reference.
3. No packaging/build dependency.
4. Replacement behavior has automated coverage where behavior was active.
5. Relevant targeted tests pass after consolidation.
6. The full suite passes before the deletion set is considered complete.

The cleanup is intentionally aggressive but evidence-based.

### 12.1 Files/directories intended for removal

After their behavior is replaced or proven unused:

- `RADMON.bat`
- `RUN_DUMMY.bat`
- `RUN_LAN.bat`
- top-level `main.py` and `central_server.py` once superseded by the packaged/source entry path
- all `radmon/*_revision.py` compatibility/monkey-patch modules
- historical dated design and implementation-plan documents under `docs/`
- obsolete tests that only enforce the old `.bat` launcher structure, replaced by production supervisor/release tests
- zero-reference legacy assets such as the old Silk icon set if asset analysis confirms no active consumer
- unused Tabler icons after registry/reference analysis
- unused demo/helper scripts such as `scripts/smoke_demo.py` if final reference/build analysis confirms no consumer
- duplicate compatibility code that becomes unreachable after consolidation

### 12.2 Files not considered dead merely because they are not packaged runtime code

- automated tests that protect current production behavior;
- CI/release workflow configuration;
- `.env.example`;
- supported installation and user documentation;
- HTML manual assets when they remain directly opened by the product;
- Grafana provisioning/compose resources when the retained external Grafana strategy still consumes them.

## 13. Documentation cleanup

All historical dated design/implementation-plan documents currently kept under `docs/` are removed by user decision rather than moved to an archive.

The final product documentation is limited to current operational material, such as:

- `README.md`
- `docs/INSTALLATION.md`
- `docs/USER-MANUAL.md`
- runtime HTML help assets only if the UI continues to use them

Documentation is updated to describe executable-based installation, startup, shutdown, external Grafana expectations, upgrade, rollback, and diagnostics. References to `.bat` launchers, `.venv`, manual `pip install`, or production `pytest` execution are removed from the production SOP.

## 14. Test strategy

Implementation follows test-driven development for new behavior and bug fixes.

### 14.1 Production supervisor tests

Automated tests cover:

- one top-level production startup path;
- single-instance protection;
- central service starts before the Admin UI becomes operational;
- GUI exit requests full RadMon-owned central shutdown;
- central service stop is idempotent;
- stale RadMon ownership can be recovered safely;
- unrelated port-8090 ownership is never killed;
- resource paths resolve correctly in development and simulated packaged contexts.

### 14.2 Patch-consolidation parity tests

Existing regression tests are used to lock current behavior before each revision module is folded into final source. The patch is removed only after the same behavior passes without the patch loader.

### 14.3 Release-layout tests

The release artifact must prove:

- `RadMon.exe` exists;
- required PyInstaller internal files exist;
- required assets are present;
- no `.bat` launcher is present;
- no `main.py` or `central_server.py` launcher is present;
- no test source or historical engineering design document is present;
- `.env` with production secrets is not bundled;
- `.env.example` is present;
- persistent production paths are not packaged in a way that causes upgrades to overwrite existing data.

### 14.4 Windows packaged smoke test

A Windows CI job builds the PyInstaller application and performs a packaged smoke validation. Where a full interactive GUI session is impractical in CI, the executable must expose or support a deterministic smoke/diagnostic path that exercises packaged imports, path resolution, configuration discovery, and central-service startup/stop without requiring live production source databases.

Physical production commissioning remains a separate final step for real MariaDB source connectivity, Grafana, detector/source write-through, operator workflow, and optional WhatsApp session behavior.

## 15. CI and release workflow

Source CI continues to run on every push/pull request and verifies:

- full pytest suite;
- Python compilation/import validation;
- Grafana payload/schema validation.

A Windows release job verifies:

- PyInstaller build;
- release layout rules;
- packaged smoke test;
- ZIP artifact creation.

A release is not described as production-ready until both source CI and the Windows packaging checks succeed.

## 16. Dependency cleanup

Dependencies are reviewed against imports and packaging needs.

The intended split is:

- runtime/application dependencies: libraries required by RadMon itself;
- development/build dependencies: `pytest`, PyInstaller, and build/test-only helpers.

A dependency is removed only after import/reference analysis and the full test/build matrix prove it is unused.

## 17. Upgrade and rollback

Before production upgrade:

- close RadMon and confirm shutdown;
- preserve `config\.env`;
- preserve `runtime\`, `archives\`, and `reports\`;
- copy the current `app\` to `backup\app-previous\`.

Upgrade replaces only `app\`.

Rollback:

1. Close the new RadMon release.
2. Replace `app\` with `backup\app-previous\`.
3. Keep persistent configuration/data untouched.
4. Launch the previous `RadMon.exe`.

Central SQLite schema changes introduced during this work must be additive/backward-safe where practical. No destructive state migration is included in this cleanup design.

## 18. Acceptance criteria

The cleanup is complete only when all of the following are true:

- Production starts by launching `RadMon.exe` only.
- No `.bat` launcher is needed or shipped.
- Production does not require a Python interpreter, virtual environment, `pip`, or manual test command.
- Closing the Admin UI causes the RadMon central API and LAN collector to stop.
- Port 8090 is not left occupied by an orphan RadMon process after normal shutdown.
- Restart after normal close succeeds without manual process cleanup.
- External Grafana integration still works through the retained supported paths.
- No source MariaDB schema change is introduced.
- Alarm policy, suppression, response, archive, reports, security, LAN ingestion, source health, Grafana projections, and notification behavior remain protected by tests.
- Persistent runtime/security/archive/report data survives restart and release replacement.
- All active `*_revision.py` behavior has been consolidated and the revision files are gone.
- `radmon/__init__.py` no longer applies monkey patches.
- Historical dated design/implementation-plan files are gone.
- Dead legacy resources and scripts identified by reference/build analysis are gone.
- Full source tests pass.
- Python compile/import validation passes.
- Grafana payload validation passes.
- Windows PyInstaller build passes.
- Packaged smoke validation passes.
- Release-layout validation passes.

## 19. Implementation sequencing

Implementation occurs on `release-cleanup`, not directly on `main`.

High-level sequence:

1. Add tests for the new production supervisor, path model, and release contract.
2. Introduce path resolution and production supervisor/central-service boundaries.
3. Move production lifecycle from the `.bat`/separate-entry-point model into the supervisor.
4. Add PyInstaller packaging and Windows release CI.
5. Consolidate revision modules into final modules incrementally with parity tests.
6. Remove obsolete launchers and superseded top-level entry points.
7. Audit and remove dead assets, scripts, dependencies, duplicate compatibility code, and obsolete launcher tests.
8. Remove historical engineering documents and update current operational docs.
9. Run the complete source and Windows release verification matrix.
10. Perform physical production commissioning before merging/deploying as the new production release.

## 20. Definition of done

For a production operator, the final system is understood as:

> Launch `RadMon.exe` to run the RadMon central system. Close `RadMon.exe` to shut down all RadMon-owned central services.

For production updates:

> Close RadMon, replace the application payload with the tested release, keep persistent configuration/data, then launch `RadMon.exe`.

The production SOP contains no `.bat`, `.venv`, manual `pip install`, production `pytest`, `main.py`, `central_server.py`, or manual orphan-process cleanup step.
