# RadMon Legacy Desktop UI Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add functional legacy desktop workflow parity to the existing secure PySide6 RadMon Admin while keeping the current central/LAN/archive/security contracts unchanged.

**Architecture:** Keep `MainWindow` as the shell and split new legacy-compatible dialogs into focused modules. `RecentPage` owns the only `Date/Time | Message` panel; security alarm refresh feeds that page instead of a global dock. Shared period/prefs/test dialogs are reusable and local runtime acquisition control is gated through `ApplicationRuntime` without ever owning LAN ingestion.

**Tech Stack:** Python 3.12, PySide6, pyserial, MariaDB repository interfaces, Qt `QSettings`, existing RadMon security/audit/report/archive services, pytest.

**Spec:** `docs/2026-09-09-legacy-desktop-ui-parity-design.md`

## Global Constraints

- Target branch is `main`.
- Message panel exists inside `RecentPage` only; no global message/alarm dock.
- Production databases remain read-only except approved ACK write-through.
- LAN collector ownership stays in `central_server.py`; desktop LAN must never start a collector.
- Production `device.serid` remains authoritative in LAN mode.
- No physical buzzer/relay/serial command writes are added.
- Existing auth, role, PIN, audit, archive, report, and Grafana behavior must remain compatible.
- About credits Hilmi Mubarok and links to `https://github.com/Mubax5` and `https://mubacs.site`.
- Repository test policy forbids keeping `docs/superpowers`; this plan intentionally lives in `docs/`.

---

### Task 1: Reusable legacy UI preferences and period selection

**Files:**
- Create: `radmon/admin/ui_preferences.py`
- Create: `radmon/admin/period_dialog.py`
- Test: `tests/test_legacy_ui_parity.py`

**Interfaces:**
- Produces `DesktopPreferences.load(settings) -> DesktopPreferences` and `.save()` using `QSettings` for non-secret display/report/server UI preferences only.
- Produces `period_preset(name: str, now: datetime) -> tuple[datetime, datetime]`.
- Produces `PeriodSelectionDialog.selection() -> tuple[datetime, datetime, str]`.

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime
from pathlib import Path

from radmon.admin.period_dialog import period_preset


def test_period_presets_calendar_boundaries():
    now = datetime(2026, 9, 9, 14, 30, 15)
    assert period_preset("Today", now) == (
        datetime(2026, 9, 9, 0, 0, 0), datetime(2026, 9, 9, 14, 30, 15)
    )
    assert period_preset("Last month", now) == (
        datetime(2026, 8, 1, 0, 0, 0), datetime(2026, 9, 1, 0, 0, 0)
    )
    assert period_preset("This year", now) == (
        datetime(2026, 1, 1, 0, 0, 0), datetime(2026, 9, 9, 14, 30, 15)
    )


def test_preferences_module_has_no_secret_fields():
    source = Path("radmon/admin/ui_preferences.py").read_text(encoding="utf-8").lower()
    for forbidden in ("db_password", "central_token", "pin_hash", "password_hash"):
        assert forbidden not in source
```

- [ ] **Step 2: Run the focused tests and confirm they fail before implementation**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py`
Expected: import/file failures for the new modules.

- [ ] **Step 3: Implement calendar presets and non-secret preference storage**

`period_preset` handles `Today`, `Yesterday`, `Last 7 days`, `This month`, `Last month`, `This year`, and `Last year` using half-open calendar boundaries where appropriate. `DesktopPreferences` stores refresh/format/color/report/server UI values only through `QSettings("RadMon", "Radiation Monitoring")`.

- [ ] **Step 4: Implement `PeriodSelectionDialog`**

Build a modal dialog with From/To `QDateTimeEdit`, grouping `QComboBox`, preset buttons, and OK/Cancel. Preset buttons call `period_preset` and update the editors.

- [ ] **Step 5: Re-run the focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py`
Expected: PASS for Task 1 tests.

---

### Task 2: Restore Recent multi-station overview and Recent-only Message panel

**Files:**
- Modify: `radmon/admin/recent_page.py`
- Modify: `radmon/secure_context.py`
- Test: `tests/test_legacy_ui_parity.py`

**Interfaces:**
- `RecentPage.set_message_rows(rows: list[tuple[datetime | str, str]]) -> None` renders the embedded message table.
- `RecentPage.refresh_live()` renders all `repository.station_configs()` rows using latest/recent data while preserving selected-station context.
- `install_window_security` updates `window.recent_page` and no longer constructs a `QDockWidget` for active alarms.

- [ ] **Step 1: Add failing source/Qt structure tests**

```python
from pathlib import Path


def test_message_panel_belongs_to_recent_only():
    recent = Path("radmon/admin/recent_page.py").read_text(encoding="utf-8")
    assert 'setObjectName("recentMessageTable")' in recent
    for path in (
        "radmon/admin/tabular_page.py", "radmon/admin/chart_page.py",
        "radmon/admin/reports_page.py", "radmon/admin/alarm_page.py",
        "radmon/admin/logs_page.py",
    ):
        assert "recentMessageTable" not in Path(path).read_text(encoding="utf-8")
    security = Path("radmon/secure_context.py").read_text(encoding="utf-8")
    assert "QDockWidget" not in security
```

- [ ] **Step 2: Run the focused test and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py::test_message_panel_belongs_to_recent_only`
Expected: FAIL because current security uses `QDockWidget` and Recent has no message table.

- [ ] **Step 3: Replace `RecentPage` layout**

Use one overview `QTableWidget` with columns `Station`, `Measurement Time`, `Dose Rate [µSv/h]`, `Avg. Dose Rate [µSv/h]`, `Approx. Dose [µSv]`, `Low Threshold`, `High Threshold`, `Alarm`, followed by a bottom `QTableWidget` named `recentMessageTable` with `Date/Time`, `Message`.

For each station, call `latest_reading`; use a short bounded history query to calculate average rate and obtain stored `dose` when available. If recent-table aggregate fields can be read cheaply, prefer them; failures render station OFFLINE instead of crashing the whole page.

- [ ] **Step 4: Route security alarm strip into Recent**

Remove `QDockWidget` creation from `install_window_security`. Its 2-second timer still queries the existing alarm mirror but calls `window.recent_page.set_message_rows(...)`. If there is no active alarm, provide an empty list.

- [ ] **Step 5: Re-run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py`
Expected: Task 1+2 tests PASS.

---

### Task 3: Add Options, Server Test, Hardware Test, About, and Acquisition Control dialogs

**Files:**
- Create: `radmon/admin/options_dialog.py`
- Create: `radmon/admin/diagnostics_dialogs.py`
- Create: `radmon/admin/about_dialog.py`
- Create: `radmon/admin/acquisition_dialog.py`
- Modify: `radmon/runtime.py`
- Modify: `radmon/collector.py`
- Test: `tests/test_legacy_ui_parity.py`
- Test: `tests/test_runtime_acquisition_gate.py`

**Interfaces:**
- `OptionsDialog(preferences, parent)` edits/saves only `DesktopPreferences`.
- `server_health_lines(url: str, timeout: float = 3.0, opener=None) -> list[str]` performs HTTP GET only.
- `hardware_test_lines(bindings, baudrate, timeout, serial_factory=None) -> list[str]` opens/reads/closes serial only and never calls `.write()`.
- `AboutDialog` exposes clickable GitHub/website links.
- `ApplicationRuntime.pause()`, `.resume()`, `.is_paused` gate detector/dummy acquisition.
- `SerialCollector.run_forever(stop_event=None, pause_event=None)` closes the port while paused.

- [ ] **Step 1: Add failing diagnostic/runtime tests**

```python

def test_about_credits_creator_and_links():
    source = Path("radmon/admin/about_dialog.py").read_text(encoding="utf-8")
    assert "Hilmi Mubarok" in source
    assert "https://github.com/Mubax5" in source
    assert "https://mubacs.site" in source


def test_hardware_probe_never_writes_serial():
    class FakeSerial:
        def __init__(self, **kwargs): self.closed = False
        def readline(self): return b""
        def write(self, *_): raise AssertionError("hardware test must never write")
        def close(self): self.closed = True
    lines = hardware_test_lines([(5201, "COM3")], 2400, 0.01, serial_factory=FakeSerial)
    assert any("COM3" in line for line in lines)


def test_runtime_pause_resume_gate():
    runtime = ApplicationRuntime(repo, settings, None, "dummy")
    assert not runtime.is_paused
    runtime.pause()
    assert runtime.is_paused
    runtime.resume()
    assert not runtime.is_paused
```

- [ ] **Step 2: Run the tests and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py tests/test_runtime_acquisition_gate.py`
Expected: missing modules/methods.

- [ ] **Step 3: Implement diagnostics dialogs**

`ServerTestDialog` displays line-oriented results in read-only `QPlainTextEdit`, Save, Close. It probes only the configured `/health` endpoint using `urllib.request.urlopen` or an injected opener. `HardwareTestDialog` enumerates configured detector bindings and performs serial open/read/close only; LAN mode displays a non-owning message.

- [ ] **Step 4: Implement About and Options**

`AboutDialog` shows app name/version text, `Creator: Hilmi Mubarok`, and clickable external links via `QDesktopServices.openUrl`. `OptionsDialog` has tabs `Display`, `File & Report`, `Server`, including color pickers and non-secret preference persistence.

- [ ] **Step 5: Implement local acquisition gate**

Add `pause_event` to `ApplicationRuntime`; dummy loop waits while paused. Pass it to `SerialCollector.run_forever`. Collector exits/closes the active serial context when pause becomes set and waits until resume. `stop()` still terminates normally.

- [ ] **Step 6: Implement Acquisition Control dialog**

For runtime `None` / source `lan`, show `LAN ingestion owned by central_server.py` and disable pause/resume. For local runtime, show source/status and toggle pause/resume.

- [ ] **Step 7: Re-run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py tests/test_runtime_acquisition_gate.py`
Expected: PASS.

---

### Task 4: Expand Station Properties and Alarm history toward legacy workflow

**Files:**
- Modify: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/admin/alarm_page.py`
- Test: `tests/test_legacy_ui_parity.py`

**Interfaces:**
- Station dialog uses tabs `Attributes`, `Alarm`, `Hardware`; saved backend fields remain limited to currently secured repository fields.
- Alarm page exposes legacy presentation columns while retaining remote row key in `Qt.UserRole` for secured ACK.

- [ ] **Step 1: Add failing structure tests**

```python

def test_station_properties_and_alarm_legacy_fields_present():
    station = Path("radmon/admin/station_admin_dialog.py").read_text(encoding="utf-8")
    for label in ("Attributes", "Alarm", "Hardware", "Audio path", "Type", "Address"):
        assert label in station
    alarm = Path("radmon/admin/alarm_page.py").read_text(encoding="utf-8")
    for label in ("Tag", "Event time", "Threshold", "Dose rate", "Hit count", "Action Time", "PIC", "Action", "Note"):
        assert label in alarm
```

- [ ] **Step 2: Run and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py::test_station_properties_and_alarm_legacy_fields_present`
Expected: FAIL on missing station tabs/fields and current alarm labels.

- [ ] **Step 3: Refactor StationAdminDialog into three tabs**

Keep existing Admin+PIN save path. Audio path/type/address are presentation/configuration fields; do not send unapproved fields into `DeviceAdminService.update_station`. LAN SERID control is read-only/disabled based on parent `source == "lan"`.

- [ ] **Step 4: Update AlarmPage controls and columns**

Add date edit + day-count control. Filter rendered remote/local events by selected range. Present legacy column order and keep source key as hidden `Qt.UserRole` data so `_ack_selected` still calls the existing secure `alarm_control.ack`.

- [ ] **Step 5: Re-run focused tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py`
Expected: PASS.

---

### Task 5: Wire full menu/toolbar parity into MainWindow and Reports/Tabular period actions

**Files:**
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/admin/tabular_page.py`
- Modify: `radmon/admin/reports_page.py`
- Modify: `main.py`
- Test: `tests/test_legacy_ui_parity.py`
- Test: existing `tests/test_admin_ui_v3.py`, `tests/test_qt_smoke.py`, report tests.

**Interfaces:**
- MainWindow receives optional `runtime` and stores named page attributes (`recent_page`, `tabular_page`, etc.).
- Page methods: optional `save_as()`, `export_csv()`, `print_preview()`, `print_report()`, `select_period()`; shell delegates only when supported.

- [ ] **Step 1: Add failing menu/action tests**

```python

def test_legacy_menu_actions_present():
    source = Path("radmon/admin/main_window.py").read_text(encoding="utf-8")
    for label in (
        "Save As...", "Save As CSV...", "Printer Setup...", "Print Preview...", "Print...",
        "Recent Values", "Tabular View", "Chart Display", "Reports", "Alarm", "Log", "Refresh",
        "Options...", "Test Server...", "Test Hardware...", "Acquisition Control...",
        "Installation Manual...", "User Manual...", "About...",
    ):
        assert label in source
```

- [ ] **Step 2: Run and confirm failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py::test_legacy_menu_actions_present`
Expected: FAIL on missing actions.

- [ ] **Step 3: Add named pages and all actions**

Instantiate pages into attributes before `addTab`. Build File/View/Tools/Help menus matching the spec and toolbar icons/actions where useful. View actions switch tabs; Refresh calls current page. Save/print actions delegate safely to the active page.

- [ ] **Step 4: Wire Options/Test/Acquisition/About**

Open the Task 3 dialogs. Server target defaults to `http://<central_host>:8090/health` and can be overridden by the desktop preference URI. `main.py` passes the local `ApplicationRuntime` to `MainWindow`; LAN passes `None`.

- [ ] **Step 5: Add period selection hooks**

Tabular and Reports expose a `select_period()` action/dialog and update their From/To editors from the result. Existing archive selector and preview-first Report behavior remain unchanged.

- [ ] **Step 6: Re-run UI/report smoke tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_legacy_ui_parity.py tests/test_admin_ui_v3.py tests/test_qt_smoke.py tests/test_report_preview.py tests/test_archive_reports_ui.py`
Expected: PASS.

---

### Task 6: Documentation, full regression, and final GitHub verification

**Files:**
- Modify: `README.md`
- Test: full suite and existing Grafana validation.

**Interfaces:**
- README documents legacy-compatible desktop workflow, Recent-only message panel, Server/Hardware Test safety, acquisition ownership, and creator links.

- [ ] **Step 1: Update README**

Document the new desktop actions, clarify that Server Test is read-only, Hardware Test never writes to detector hardware, LAN Acquisition Control cannot start a collector, and the Recent Message panel is not global.

- [ ] **Step 2: Run full tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: 0 failures.

- [ ] **Step 3: Compile Python**

Run: `python -m compileall -q main.py central_server.py radmon`
Expected: exit code 0.

- [ ] **Step 4: Run Grafana payload validation**

Run the same assertions as `.github/workflows/ci.yml`: 3 logical pages, 5 Operations variants, 7 dashboards, 2s refresh, 15 playlist items, 10s interval, YAML parse success.
Expected: `Grafana TV payloads valid`.

- [ ] **Step 5: Push final implementation to `main` and wait for GitHub CI**

Confirm final `main` SHA, GitHub Actions conclusion `success`, full test count, compile success, and Grafana validation success before claiming completion.
