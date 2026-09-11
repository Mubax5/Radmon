# RadMon Tabler Icon System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace reused/catch-all Silk UI icons with a local semantic Tabler Outline registry so distinct RadMon features and commands use distinct, consistent icons.

**Architecture:** Vendor only the approved Tabler Outline SVG subset as local assets, load them through one `app_icon(slot)` semantic registry, and migrate every visible desktop action/tab/tree/dialog icon away from raw filenames and `silk_icon()`. Reuse is allowed only for the exact same action exposed in multiple locations, such as one Refresh `QAction` shown in both menu and toolbar.

**Tech Stack:** PySide6 `QIcon`, local SVG assets, Tabler Icons MIT license, pytest/Qt offscreen smoke tests.

**Spec:** `docs/superpowers/specs/2026-09-11-alarm-policy-suppression-icon-system-design.md`

## Global Constraints

- All migrated visible icons use the **Tabler Outline** family only.
- Assets are local; there is no runtime network dependency.
- Distinct features/commands have distinct semantic slots and distinct icon files.
- The same icon may be reused only when it is literally the same action shown in multiple UI locations.
- Station group, detector child, Monitoring, Server Test, Alarm, and Suppress Alarm must all differ.
- Station Properties, Application Options, and Printer Setup must all differ.
- No generic `feed`, `monitor`, `lock`, or similar catch-all icon may remain mapped to unrelated visible features.
- No emoji literals are used as UI icons.
- Existing action labels, shortcuts, permissions, and behavior must not change as part of the icon migration.

---

## File Map

- Create directory `radmon/admin/icons/tabler/` containing the approved SVG subset and `LICENSE.txt`.
- Modify `radmon/admin/icons.py`: replace filename-oriented public API with semantic `ICON_SLOTS` and `app_icon(slot)`; keep a temporary private compatibility loader only if a non-visible legacy call remains during the same task.
- Modify `radmon/admin/main_window.py`: tabs, tree nodes, menus, toolbar, tools/help actions.
- Modify `radmon/secure_context.py`: Edit Station, Users, Logout.
- Modify `radmon/admin/auth_dialogs.py`: login/security window icon.
- Modify `radmon/admin/alarm_response_dialog.py`: alarm response icon.
- Modify `radmon/admin/alarm_page.py`: Alarm/ACK and, when present from the alarm-policy plan, Suppress Alarm.
- Modify `radmon/admin/station_admin_dialog.py`: station properties icon.
- Modify `radmon/admin/user_admin_dialog.py`: user/security icon.
- Modify other `radmon/admin/*.py` call sites returned by a repository-wide `silk_icon(` search.
- Test: `tests/test_icon_registry.py`.
- Modify: `tests/test_qt_smoke.py`, `tests/test_admin_ui_v3.py`.

---

### Task 1: Vendor the approved Tabler Outline subset and build the semantic icon registry

**Files:**
- Create: `radmon/admin/icons/tabler/LICENSE.txt`
- Create: `radmon/admin/icons/tabler/*.svg` for every mapping below
- Modify: `radmon/admin/icons.py`
- Test: `tests/test_icon_registry.py`

**Interfaces:**
- Produces: `ICON_SLOTS: dict[str, str]` mapping semantic slots to Tabler asset basenames.
- Produces: `app_icon(slot: str) -> QIcon`.
- Produces: `icon_path(slot: str) -> Path` for deterministic tests/diagnostics.

- [ ] **Step 1: Write failing registry tests**

```python
# tests/test_icon_registry.py
from PySide6.QtWidgets import QApplication
from radmon.admin.icons import ICON_SLOTS, app_icon, icon_path


def app():
    return QApplication.instance() or QApplication([])


def test_all_registry_icons_are_local_tabler_svg_and_load():
    app()
    for slot in ICON_SLOTS:
        path = icon_path(slot)
        assert path.parent.name == "tabler"
        assert path.suffix == ".svg"
        assert path.is_file(), slot
        assert not app_icon(slot).isNull(), slot


def test_primary_feature_slots_are_semantically_unique():
    slots = [
        "monitoring", "station_group", "detector", "recent", "tabular",
        "chart", "reports", "alarm", "suppress_alarm", "logs",
        "station_properties", "users", "archive", "refresh", "server_test",
        "hardware_test", "acquisition", "installation_manual", "user_manual", "exit",
    ]
    paths = [icon_path(slot).name for slot in slots]
    assert len(paths) == len(set(paths))


def test_settings_related_commands_do_not_share_icons():
    names = {
        icon_path("station_properties").name,
        icon_path("application_options").name,
        icon_path("printer_setup").name,
    }
    assert len(names) == 3


def test_unknown_slot_fails_loudly():
    import pytest
    with pytest.raises(KeyError):
        app_icon("not-a-real-slot")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_icon_registry.py`
Expected: FAIL because the semantic registry/assets do not exist.

- [ ] **Step 3: Retrieve and vendor the exact approved SVGs**

Use the icon tool with exact refs, not guessed filenames, for each approved Tabler Outline icon. Save only the returned SVG markup into `radmon/admin/icons/tabler/<id>.svg`.

Approved registry:

```python
ICON_SLOTS = {
    "monitoring": "chart-line",
    "station_group": "server",
    "detector": "radioactive",
    "recent": "activity",
    "tabular": "database",
    "chart": "chart-area-line",
    "reports": "file-chart",
    "alarm": "alarm",
    "suppress_alarm": "bell-cancel",
    "logs": "logs",
    "station_properties": "settings-cog",
    "users": "users",
    "archive": "archive",
    "refresh": "refresh",
    "server_test": "server-cog",
    "hardware_test": "cpu-2",
    "acquisition": "device-analytics",
    "installation_manual": "book-2",
    "user_manual": "help-circle",
    "exit": "logout",
    "save_as": "file-export",
    "save_csv": "table-export",
    "printer_setup": "settings-2",
    "print_preview": "eye-check",
    "print": "printer",
    "select_period": "calendar",
    "new_station": "plus",
    "application_options": "settings",
    "about": "file-info",
}
```

Also vendor the Tabler Icons MIT license text to `LICENSE.txt`. Do not mix in Silk PNGs, emojis, Material, Lucide, or other families for these slots.

- [ ] **Step 4: Implement `app_icon()`**

Replace the public loader with:

```python
from pathlib import Path
from PySide6.QtGui import QIcon

_ICON_ROOT = Path(__file__).with_name("icons") / "tabler"


def icon_path(slot: str) -> Path:
    icon_id = ICON_SLOTS[slot]
    return _ICON_ROOT / f"{icon_id}.svg"


def app_icon(slot: str) -> QIcon:
    path = icon_path(slot)
    if not path.is_file():
        raise FileNotFoundError(f"Tabler icon asset missing for {slot}: {path}")
    return QIcon(str(path))
```

Fail loudly for missing assets during development rather than returning a silent null icon.

- [ ] **Step 5: Run registry tests**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_icon_registry.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add radmon/admin/icons.py radmon/admin/icons/tabler tests/test_icon_registry.py
git commit -m "feat: add semantic Tabler icon registry"
```

---

### Task 2: Migrate every visible desktop icon call site to semantic slots

**Files:**
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/secure_context.py`
- Modify: `radmon/admin/auth_dialogs.py`
- Modify: `radmon/admin/alarm_response_dialog.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/admin/user_admin_dialog.py`
- Modify: any additional visible `radmon/admin/*.py` file returned by `silk_icon(` search
- Test: `tests/test_admin_ui_v3.py`
- Test: `tests/test_qt_smoke.py`

**Interfaces:**
- Consumes: `app_icon(slot)` from Task 1.
- No action semantics or permissions change.

- [ ] **Step 1: Update source-level UI tests to require semantic slots and ban visible Silk reuse**

Replace the old Silk assertions with tests equivalent to:

```python
from pathlib import Path


def read(path):
    return Path(path).read_text(encoding="utf-8")


def test_main_window_uses_distinct_semantic_icons():
    source = read("radmon/admin/main_window.py")
    for slot in (
        "monitoring", "station_group", "detector", "recent", "tabular", "chart",
        "reports", "alarm", "logs", "refresh", "server_test", "hardware_test",
        "acquisition", "installation_manual", "user_manual", "exit", "save_as",
        "save_csv", "printer_setup", "print_preview", "print", "select_period",
        "new_station", "application_options", "about",
    ):
        assert f'app_icon("{slot}")' in source
    assert "silk_icon(" not in source
    assert 'app_icon("station_group")' in source
    assert 'app_icon("detector")' in source


def test_security_context_uses_specific_security_icons():
    source = read("radmon/secure_context.py")
    assert 'app_icon("station_properties")' in source
    assert 'app_icon("users")' in source
    assert 'app_icon("exit")' in source
    assert "silk_icon(" not in source
```

- [ ] **Step 2: Run tests and verify failure**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_admin_ui_v3.py tests/test_qt_smoke.py tests/test_icon_registry.py`
Expected: FAIL because call sites still use `silk_icon`.

- [ ] **Step 3: Migrate `main_window.py` with exact slot mapping**

Use:

```python
from .icons import app_icon
```

Tabs:

```python
self.tabs.addTab(self.recent_page, app_icon("recent"), "Recent")
self.tabs.addTab(self.tabular_page, app_icon("tabular"), "Tabular")
self.tabs.addTab(self.chart_page, app_icon("chart"), "Chart")
self.tabs.addTab(self.reports_page, app_icon("reports"), "Reports")
self.tabs.addTab(self.alarm_page, app_icon("alarm"), "Alarm")
self.tabs.addTab(self.logs_page, app_icon("logs"), "Logs")
```

Station tree:

```python
root.setIcon(0, app_icon("station_group"))
child.setIcon(0, app_icon("detector"))
```

Actions:

```python
self.monitoring_action = QAction(app_icon("monitoring"), "Monitoring", self)
self.refresh_action = QAction(app_icon("refresh"), "Refresh", self)
self.save_as_action = QAction(app_icon("save_as"), "Save As...", self)
self.save_csv_action = QAction(app_icon("save_csv"), "Save As CSV...", self)
self.printer_setup_action = QAction(app_icon("printer_setup"), "Printer Setup...", self)
self.print_preview_action = QAction(app_icon("print_preview"), "Print Preview...", self)
self.print_action = QAction(app_icon("print"), "Print...", self)
self.exit_action = QAction(app_icon("exit"), "Exit", self)
self.select_period_action = QAction(app_icon("select_period"), "Select period...", self)
self.new_station_action = QAction(app_icon("new_station"), "New station...", self)
self.options_action = QAction(app_icon("application_options"), "Options...", self)
self.server_test_action = QAction(app_icon("server_test"), "Test Server...", self)
self.hardware_test_action = QAction(app_icon("hardware_test"), "Test Hardware...", self)
self.acquisition_action = QAction(app_icon("acquisition"), "Acquisition Control...", self)
self.install_manual_action = QAction(app_icon("installation_manual"), "Installation Manual...", self)
self.user_manual_action = QAction(app_icon("user_manual"), "User Manual...", self)
self.about_action = QAction(app_icon("about"), "About...", self)
```

The `view_actions` tuple must use semantic slots `recent`, `tabular`, `chart`, `reports`, `alarm`, `logs` rather than filenames.

- [ ] **Step 4: Migrate security/admin/dialog call sites**

Use exact semantic intent:

```python
# secure_context.py
edit_station = QAction(app_icon("station_properties"), "Edit Station", window)
manage_users = QAction(app_icon("users"), "Users", window)
logout = QAction(app_icon("exit"), "Logout / Exit", window)

# auth_dialogs.py
self.setWindowIcon(app_icon("users"))

# alarm_page.py / alarm_response_dialog.py
self.ack_button = QPushButton(app_icon("alarm"), "ACK / Response")
# when suppression UI exists:
self.suppress_button = QPushButton(app_icon("suppress_alarm"), "Suppress Alarm...")

# station_admin_dialog.py
self.setWindowIcon(app_icon("station_properties"))

# user_admin_dialog.py
self.setWindowIcon(app_icon("users"))
```

If the alarm-policy plan has not been implemented yet, keep `suppress_alarm` in the registry and add its call when Task 7 of that plan creates the suppression button; do not invent a temporary Silk fallback.

- [ ] **Step 5: Repository-wide visible call-site check**

Run: `git grep -n "silk_icon(" -- radmon/admin radmon/secure_context.py radmon/production_integration_revision.py radmon/production_integration_compat_revision.py`

Expected: no live UI call uses Silk for migrated visible features. If a compatibility patch still injects `feed`, `monitor`, or `lock`, change that patch to call `app_icon()` with the same semantic slot as the base UI. Do not delete the old Silk license/assets in this task unless there are zero remaining compatibility references outside visible UI.

- [ ] **Step 6: Run UI tests**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_icon_registry.py tests/test_admin_ui_v3.py tests/test_qt_smoke.py tests/test_admin_startup_smoke.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/admin radmon/secure_context.py radmon/production_integration_revision.py radmon/production_integration_compat_revision.py tests/test_admin_ui_v3.py tests/test_qt_smoke.py
git commit -m "refactor: use distinct semantic icons across admin ui"
```

---

### Task 3: Lock icon-family/uniqueness regressions and run the full suite

**Files:**
- Modify: `tests/test_icon_registry.py`
- Modify: `README.md`

**Interfaces:**
- No new runtime interface; this task makes the visual contract test-enforced.

- [ ] **Step 1: Add a registry contract test for all approved mappings**

```python
EXPECTED = {
    "monitoring":"chart-line", "station_group":"server", "detector":"radioactive",
    "recent":"activity", "tabular":"database", "chart":"chart-area-line",
    "reports":"file-chart", "alarm":"alarm", "suppress_alarm":"bell-cancel",
    "logs":"logs", "station_properties":"settings-cog", "users":"users",
    "archive":"archive", "refresh":"refresh", "server_test":"server-cog",
    "hardware_test":"cpu-2", "acquisition":"device-analytics",
    "installation_manual":"book-2", "user_manual":"help-circle", "exit":"logout",
    "save_as":"file-export", "save_csv":"table-export", "printer_setup":"settings-2",
    "print_preview":"eye-check", "print":"printer", "select_period":"calendar",
    "new_station":"plus", "application_options":"settings", "about":"file-info",
}


def test_registry_matches_approved_design_exactly():
    from radmon.admin.icons import ICON_SLOTS
    assert ICON_SLOTS == EXPECTED
```

- [ ] **Step 2: Add source scan test banning catch-all visible icon mappings**

Scan visible UI Python sources and assert none contain these old usages:

```python
for forbidden in ('silk_icon("feed")', 'silk_icon("monitor")', 'silk_icon("lock")'):
    assert forbidden not in visible_source
```

Do not ban words such as `monitor` in normal function names; ban only old icon calls.

- [ ] **Step 3: Document the icon contract**

Add to README UI notes:

```text
Desktop icons use a vendored Tabler Outline subset through semantic `app_icon()` slots.
Distinct RadMon features intentionally use distinct symbols; asset filenames are not referenced directly by UI code.
```

- [ ] **Step 4: Run full CI-equivalent validation**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: all tests PASS.

Run: `python -m compileall -q main.py central_server.py radmon`
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add tests/test_icon_registry.py README.md
git commit -m "test: lock Tabler icon semantics"
```

- [ ] **Step 6: Verify exact final `main` SHA in GitHub Actions**

Push `main` and confirm the repository CI is green for that exact commit SHA. The icon migration requires no production-network verification; a visual smoke check on the Windows Admin UI is still recommended after automated tests pass.
