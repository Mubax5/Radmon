# Report, Grafana, and Multi-Station Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Reports responsive and full-width, make Grafana self-provisioning and reliably open the bundled monitoring dashboard, and support the complete Station -> detector-room hierarchy plus fleet dummy/multi-detector acquisition.

**Architecture:** Keep the existing `ipradmon` schema. Add a canonical station catalog for the 15 detector locations visible in the DPFK monitoring reference, seed only missing `device` rows, and expose those stations to Admin/Grafana. Decouple report preview refresh from the global 2-second timer and cap rich-text preview rows while retaining exact SQL aggregates. Add a Grafana bootstrap manager that first attempts the configured local Grafana and otherwise starts the bundled Docker Grafana on an isolated fallback port, verifies the dashboard UID before opening it, and never silently swallows startup failures.

**Tech Stack:** Python 3.12, PySide6, MariaDB, PyQtGraph, Grafana 13.1.3, Docker Compose, pytest.

**Spec:** User-provided screenshots in the 2026-09-07 conversation: classic Admin tree with `Station` parent and detector rooms as children; report preview centered/full-width; real-time monitoring cards with `µSv/h`.

## Global Constraints

- Keep existing `ipradmon` tables only; no new application tables.
- Keep exactly `RADMON.bat` and `RUN_DUMMY.bat` as operator BAT launchers.
- Keep acquisition/Admin/Grafana refresh cadence at 2 seconds.
- Use `µSv/h` in operator-facing units.
- Existing device rows must not be overwritten when seeding missing station metadata.
- Dummy mode must generate data for the complete station catalog.
- Real detector mode must remain backward-compatible with one detector and accept optional multi-port bindings.

---

### Task 1: Station catalog and Admin hierarchy

**Files:**
- Create: `radmon/stations.py`
- Modify: `radmon/repository.py`
- Modify: `radmon/admin/main_window.py`
- Test: `tests/test_station_catalog.py`
- Test: `tests/test_admin_ui_v3.py`

**Interfaces:**
- Produces: `STATION_CATALOG`, `station_catalog()`, `MariaDBRepository.ensure_station_catalog()`, `MariaDBRepository.station_configs()`.
- Admin consumes `station_configs()` to render one `Station` parent with detector-room children.

- [ ] Write failing tests asserting all 15 reference detector IDs/names/locations exist, units use `µSv/h`, repository seeding is insert-only for existing rows, and Admin uses `QTreeWidget` with a `Station` parent.
- [ ] Run focused tests and confirm RED.
- [ ] Implement the catalog, repository APIs, Station tree, selection details, and selected-station propagation to page settings.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 2: Responsive full-width Reports

**Files:**
- Modify: `radmon/reports.py`
- Modify: `radmon/admin/reports_page.py`
- Test: `tests/test_report_preview.py`
- Test: `tests/test_qt_smoke.py`

**Interfaces:**
- `ReportService.preview_html(..., limit=250)` returns a bounded full-width rich-text preview while `_summary_for_range()` keeps exact full-range SQL aggregates.
- `ReportsPage.refresh_live()` updates the live end time only; it never rebuilds the preview every two seconds.

- [ ] Write failing tests for full-width `width="100%"` centered tables, `µSv/h` labels, bounded preview detail, and no automatic `build_preview()` call from `refresh_live()`.
- [ ] Run focused tests and confirm RED.
- [ ] Implement rich-text layout and decouple report preview generation from the 2-second global refresh.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 3: Grafana self-provisioning and reliable Admin open

**Files:**
- Create: `radmon/grafana_bootstrap.py`
- Modify: `radmon/config.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `grafana/docker-compose.yml`
- Modify: `grafana/dashboards/radiation-monitoring.json`
- Modify: `.env.example`
- Modify: `RADMON.bat`
- Modify: `RUN_DUMMY.bat`
- Test: `tests/test_grafana_monitoring.py`
- Test: `tests/test_launchers_v3.py`

**Interfaces:**
- `GrafanaBootstrap.ensure() -> str` returns a verified dashboard URL only after the dashboard UID is reachable.
- Default local target remains port 3000; bundled Docker fallback uses port 3300 to avoid collisions with an unrelated local Grafana.

- [ ] Write failing tests asserting the manager verifies dashboard UID, uses a collision-safe fallback port, launchers no longer swallow Docker failures blindly, Admin uses the verified URL, and dashboard cards/graphs display `µSv/h`.
- [ ] Run focused tests and confirm RED.
- [ ] Implement local-import/verification plus Docker fallback, async Admin preparation, and the DPFK-style real-time dashboard layout.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 4: Fleet dummy and configurable real detectors

**Files:**
- Modify: `radmon/config.py`
- Modify: `radmon/runtime.py`
- Modify: `main.py`
- Test: `tests/test_dummy_fleet.py`
- Test: `tests/test_runtime_v2.py`

**Interfaces:**
- Dummy runtime iterates all `station_configs()` using one independent `DummyDoseGenerator` and `AlarmService` per detector.
- `Settings.detector_bindings()` parses optional `RADMON_DETECTORS` entries like `5201@COM15;5202@COM16`; when absent, the legacy single `RADMON_SERID` + `RADMON_SERIAL_PORT` path remains unchanged.

- [ ] Write failing tests for complete dummy fleet output and backward-compatible/multi-port detector binding parsing.
- [ ] Run focused tests and confirm RED.
- [ ] Implement fleet runtime and detector binding support.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 5: Full verification

- [ ] Run the entire pytest suite in GitHub Actions.
- [ ] Run Python compile validation.
- [ ] Validate Grafana JSON/YAML.
- [ ] Confirm PR is mergeable and report any environment-only limitation (physical COM hardware and local Docker/MariaDB reachability cannot be exercised in CI).
