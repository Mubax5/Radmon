# Admin UI and Grafana Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Python admin application match the established DPFK desktop workflow more closely, add mature iconography and interactive charts, make report preview first-class before print/export, and move public monitoring to Grafana.

**Architecture:** Keep acquisition, alarm handling, reporting data, and synchronization in Python against the existing `ipradmon` schema. The desktop admin stays PySide6, but gains a classic menu/toolbar shell, vendored FamFamFam Silk PNG icons, a PyQtGraph chart, and an embedded HTML report preview whose document is reused for printing and PDF export. Public monitoring is removed from the Python runtime and replaced by a provisioned Grafana dashboard that queries `device`, `measurement`, `recent`, and `alarm` directly.

**Tech Stack:** Python, PySide6, PyQtGraph, MariaDB, ReportLab, Grafana, built-in Grafana MySQL datasource.

**Spec:** Approved in chat on 2026-09-07.

## Global Constraints

- Use only the existing user-supplied `ipradmon` schema; do not add `radmon_*` database tables.
- All live acquisition/data refresh intervals are 2 seconds.
- Do not use emoji as UI icons.
- Use vendored FamFamFam Silk 16x16 PNG icons with attribution.
- Public monitoring is Grafana, not the custom FastAPI fullscreen page.
- Preserve the two operator launchers: `RADMON.bat` and `RUN_DUMMY.bat`.
- Background refresh errors must not create modal popup spam.
- Report preview must be visible before Print or Export PDF is enabled.

---

### Task 1: Classic Desktop Shell and Icons

**Files:**
- Create: `radmon/admin/icons.py`
- Create: `radmon/admin/icons/silk/*.png`
- Create: `radmon/admin/icons/silk/LICENSE.txt`
- Modify: `radmon/admin/main_window.py`
- Test: `tests/test_admin_ui_v3.py`

**Interfaces:**
- Produces `silk_icon(name: str) -> QIcon` and `silk_path(name: str) -> Path`.
- MainWindow exposes menu actions for Monitoring, Refresh, Reports, Print, and Exit and icon-bearing tabs.

- [ ] Write failing tests asserting each tab uses `QIcon`, Silk asset names are present, the toolbar/menu exists, the Station sidebar has a feed icon, and no emoji literals are used for action icons.
- [ ] Run `pytest -q tests/test_admin_ui_v3.py` and confirm failure.
- [ ] Add the icon loader, vendor only the required Silk icons plus attribution, and build `File / View / Tools / Help` plus the classic toolbar.
- [ ] Run focused tests and existing admin/runtime tests.
- [ ] Commit `feat: add classic icon-based admin shell`.

### Task 2: Interactive PyQtGraph Chart

**Files:**
- Create: `radmon/admin/chart_state.py`
- Replace: `radmon/admin/chart_page.py`
- Modify: `requirements.txt`
- Test: `tests/test_chart_interaction.py`

**Interfaces:**
- `ChartViewport` tracks live/manual range without PySide dependencies.
- `ChartPage.refresh_live()` updates data every 2 seconds without resetting a manually zoomed/panned viewport.

- [ ] Write failing tests for viewport preservation, 2-second live follow behavior, PyQtGraph dependency, crosshair/hover hooks, wheel zoom/pan support, dual axes, and threshold lines.
- [ ] Run focused tests and confirm failure.
- [ ] Implement a PyQtGraph plot with Dose rate on the left axis, Approx. Dose on the right axis, crosshair + nearest-point tooltip, mouse zoom/pan, reset view, live follow, and alert/alarm lines.
- [ ] Run focused and regression tests.
- [ ] Commit `feat: make radiation chart interactive`.

### Task 3: Preview-First Reports and Print Parity

**Files:**
- Replace: `radmon/admin/reports_page.py`
- Modify: `radmon/reports.py`
- Test: `tests/test_report_preview.py`

**Interfaces:**
- `ReportService.preview_html(start, end) -> str` creates the report document from the selected range.
- ReportsPage renders that HTML in `QTextBrowser`; Print and PDF output reuse the same `QTextDocument` after Preview succeeds.

- [ ] Write failing tests for the DPFK-style Summary + Dose rate and Approx. Dose sections, disabled Print/PDF before Preview, and same-document print/PDF flow.
- [ ] Run focused tests and confirm failure.
- [ ] Implement the embedded preview with centered installation heading, summary table, selected-station detail table, Preview/Print/Export PDF/CSV controls, and explicit range handling.
- [ ] Preserve existing CSV and programmatic ReportLab PDF APIs for compatibility tests.
- [ ] Run focused and report regression tests.
- [ ] Commit `feat: add preview-first report workflow`.

### Task 4: Grafana Public Monitoring

**Files:**
- Create: `grafana/docker-compose.yml`
- Create: `grafana/provisioning/datasources/ipradmon.yaml`
- Create: `grafana/provisioning/dashboards/radmon.yaml`
- Create: `grafana/dashboards/radiation-monitoring.json`
- Create: `grafana/README.md`
- Modify: `radmon/config.py`
- Modify: `radmon/runtime.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `.env.example`
- Test: `tests/test_grafana_monitoring.py`

**Interfaces:**
- `Settings.grafana_url` points the desktop Monitoring action to Grafana.
- Python runtime no longer starts `create_public_app` or Uvicorn.
- Dashboard refresh is `2s` and queries only `device`, `measurement`, `recent`, and `alarm`.

- [ ] Write failing tests for absence of FastAPI public runtime startup, Grafana URL wiring, 2-second dashboard refresh, MySQL provisioning, selected-station cards with sparkline/time, notification panel, and main multi-series time graph.
- [ ] Run focused tests and confirm failure.
- [ ] Remove public monitoring startup from `ApplicationRuntime`, add Grafana URL/action wiring, and add provisioning/dashboard files using the existing schema only.
- [ ] Run focused and runtime regression tests.
- [ ] Commit `feat: move public monitoring to Grafana`.

### Task 5: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_bundle.py`
- Test: `tests/test_runtime_v2.py`

**Interfaces:**
- Documentation describes only the operator workflow and Grafana deployment needed for production/demo operation.

- [ ] Update tests whose old expectations explicitly require FastAPI public monitoring.
- [ ] Document the two launchers, report preview workflow, interactive chart controls, Grafana provisioning, and 2-second refresh.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`.
- [ ] Run `python -m compileall -q main.py radmon` and JSON/YAML parse checks for Grafana assets.
- [ ] Run `git diff --check` and review the branch diff against main.
- [ ] Commit `docs: finalize admin and Grafana workflow`.
