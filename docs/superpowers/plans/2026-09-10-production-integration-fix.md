# RadMon Production Integration Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC3 station editing, PIN security, LAN live/history ingestion, alarm response, offline recovery, Grafana charts, refresh, and HTML manuals work end-to-end against production `ipradmon` sources.

**Architecture:** Preserve the current central-server ownership and split live/backfill workers. Add source-aware write-through services and an in-memory sensitive-operation lease; keep `vrecent` authoritative for live state and `measurement` authoritative for history/charts. Update the desktop tree and Grafana queries to consume live database metadata rather than frozen UI/catalog values.

**Tech Stack:** Python 3.14, MariaDB connector, PySide6, FastAPI/Uvicorn, SQLite security sidecar, Grafana JSON generator, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-10-production-integration-fix-design.md`

## Global Constraints

- Database name remains `ipradmon`.
- PC3 remains central host `192.168.1.2`.
- Production LAN sources remain configured by `RADMON_LAN_SOURCES`; no hard-coded passwords.
- Realtime `vrecent` and alarm polling remain 2 seconds by default.
- Historical backfill remains separate, incremental, checkpointed, and bounded.
- Normal source operations are reads; approved writes are Station Properties and one-step alarm response only.
- Station tree membership is derived from source mappings, not SERID ranges.
- Sensitive PIN elevation lasts 600 seconds and is in-memory only.
- `ack` is preserved during alarm response; `i_flag` changes from 0 to 1.

---

### Task 1: Ten-minute sensitive PIN lease

**Files:**
- Modify: `radmon/security.py`
- Modify: `radmon/admin/auth_dialogs.py`
- Modify: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/user_admin_dialog.py`
- Modify: `radmon/secure_context.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Produces: `SecurityStore.sensitive_lease_active(identity) -> bool`, `SecurityStore.clear_sensitive_lease(username=None) -> None`, and updated `require_sensitive(identity, permission, pin)` which grants/uses a 600-second lease.
- Produces: UI helper `sensitive_pin(parent, security, identity, *, title, message) -> tuple[str, bool]` returning `("", True)` when an active lease exists.

- [ ] **Step 1: Write failing lease tests** covering first PIN grant, reuse with empty PIN before 600 seconds, expiry, invalid PIN, role enforcement, and explicit clear.
- [ ] **Step 2: Run `pytest tests/test_security.py -q` and confirm the new tests fail because lease APIs do not exist.**
- [ ] **Step 3: Implement in-memory lease timestamps in `SecurityStore`; keep role checks on every sensitive call and clear lease on disable/revoke/logout.**
- [ ] **Step 4: Replace direct `PinDialog.get_pin()` calls in Station, Alarm, and User Admin with the lease-aware helper.**
- [ ] **Step 5: Run security/UI-focused tests and commit.**

### Task 2: Source-aware Station Properties write-through

**Files:**
- Modify: `radmon/security.py`
- Modify: `radmon/lan.py` or `radmon/lan_revision.py`
- Modify: `radmon/device_admin.py`
- Modify: `radmon/secure_services.py`
- Modify: `radmon/admin/station_admin_dialog.py`
- Test: `tests/test_device_admin.py`
- Test: `tests/test_lan.py`

**Interfaces:**
- Produces: `SecurityStore.station_source(central_serid) -> tuple[source_id, remote_serid] | None`, rejecting ambiguous mapping.
- Produces: `RemoteMariaDBSource.get_device(serid)` and `update_device(serid, changes)` for allowlisted logical fields.
- Produces: `WriteThroughDeviceAdminService.update_station(...)`, which updates source first and central second.

- [ ] **Step 1: Write failing tests asserting a LAN edit updates source before central, central remains unchanged on source error, and source-confirmed thresholds are returned.**
- [ ] **Step 2: Write a failing test asserting LAN hardware identity fields are not writable.**
- [ ] **Step 3: Run focused tests and confirm failures.**
- [ ] **Step 4: Implement source mapping lookup, remote device read/update, and write-through service.**
- [ ] **Step 5: Wire LAN secure services to the write-through service while preserving local/dummy behavior.**
- [ ] **Step 6: Make LAN `serid`, hardware address/type read-only in Station Properties; logical fields remain editable.**
- [ ] **Step 7: Run focused tests and commit.**

### Task 3: Live sample insertion for immediate charts

**Files:**
- Modify: `radmon/lan_revision.py`
- Test: `tests/test_lan.py`
- Test: `tests/test_vrecent_contract.py`

**Interfaces:**
- Produces: `MariaCentralStore.upsert_live_rows()` that both upserts `recent` and `INSERT IGNORE`s each current `vrecent` sample into `measurement` without modifying `recent` from historical backfill.

- [ ] **Step 1: Write failing tests proving one live row updates `recent` and inserts the current measurement exactly once.**
- [ ] **Step 2: Write a failing test proving an older backfill row cannot roll `recent.dtom` backward.**
- [ ] **Step 3: Run focused tests and confirm failures.**
- [ ] **Step 4: Implement idempotent live measurement insert using source `dtom/doserate/dose`; derive safe defaults for fields absent from `vrecent`.**
- [ ] **Step 5: Run focused tests and commit.**

### Task 4: Production alarm `i_flag` synchronization and one-step response

**Files:**
- Modify: `radmon/lan_revision.py`
- Modify: `radmon/remote_alarm.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/alarm_response_dialog.py`
- Test: `tests/test_remote_alarm.py`
- Test: `tests/test_lan.py`

**Interfaces:**
- Produces: `RemoteMariaDBSource.active_alarms()` returning production alarm rows where `i_flag=0`.
- Produces: `RemoteMariaDBSource.respond_alarm(...)` performing `i_op/pic/note/i_flag=1` while preserving `ack`.
- Produces: mirror state with explicit `is_active`/handled semantics derived from `i_flag`.

- [ ] **Step 1: Write failing tests asserting source SQL updates `i_flag=1`, leaves `ack` untouched, and refuses rows already handled.**
- [ ] **Step 2: Write failing tests that active rows are synchronized every live poll and rows no longer active become handled centrally.**
- [ ] **Step 3: Run focused tests and confirm failures.**
- [ ] **Step 4: Implement lightweight active-alarm refresh in addition to incremental historical checkpoint ingest.**
- [ ] **Step 5: Implement one-step response and mirror update only after source success; retain Action in central mirror/audit and prefix/append it to source note.**
- [ ] **Step 6: Ensure Submit/Enter executes the response once and refreshes UI.**
- [ ] **Step 7: Run focused tests and commit.**

### Task 5: Three collapsible source parents and complete Refresh

**Files:**
- Modify: `radmon/admin/main_window.py`
- Modify: `radmon/secure_context.py`
- Modify: `radmon/security.py`
- Test: `tests/test_admin_main_window.py` or create focused tree-model helper tests.

**Interfaces:**
- Produces: source-parent tree generated from configured source health + `source_station_map` and station configs.
- Produces: `MainWindow.refresh_all()` for F5/manual refresh; auto refresh remains current-page/live only.

- [ ] **Step 1: Extract/test a pure station grouping helper using source mappings, including the observed `.50/.38/.52` groups without SERID-range assumptions.**
- [ ] **Step 2: Write failing test for preserving parent expanded/collapsed state across tree reload.**
- [ ] **Step 3: Implement source parent items with host/state labels/tooltips and detector child items. Parent selection must not be treated as a detector.**
- [ ] **Step 4: Connect F5/Refresh to `refresh_all()` so tree, selected details, messages/health, and current page reload together.**
- [ ] **Step 5: Run focused UI/helper tests and commit.**

### Task 6: Offline recovery and database-driven Grafana

**Files:**
- Modify: `radmon/grafana_revision.py`
- Modify: `radmon/grafana_tv.py` only where generator structure requires it
- Modify: `radmon/admin/chart_page.py` if current-point fallback is needed
- Test: `tests/test_grafana_tv.py`
- Test: `tests/test_vrecent_contract.py`
- Test: status tests

**Interfaces:**
- Grafana current status always evaluates fresh `vrecent.dtom` and DB thresholds.
- Trend/sparkline panels read central `measurement` and receive current points from Task 3.

- [ ] **Step 1: Write failing tests ensuring generated realtime/operations SQL uses `vrecent.warnlevel/alarmlevel` rather than catalog literal thresholds and current station metadata comes from DB queries.**
- [ ] **Step 2: Write status/recovery test showing stale row -> OFFLINE then newer current row -> NORMAL/ALERT/ALARM on next refresh.**
- [ ] **Step 3: Implement dynamic Grafana threshold/status queries and ensure station edit becomes visible without dashboard regeneration where possible.**
- [ ] **Step 4: Ensure chart live range shows newly inserted current measurement while backfill is still old.**
- [ ] **Step 5: Regenerate/validate dashboard payloads and commit.**

### Task 7: Browser HTML manuals and non-placeholder controls

**Files:**
- Create: `docs/manual/installation.html`
- Create: `docs/manual/user-manual.html`
- Create: `docs/manual/manual.css`
- Modify: `radmon/admin/main_window.py`
- Test: manual path/launcher tests

**Interfaces:**
- Desktop Help opens local HTML manuals using existing external URL/file launcher behavior.

- [ ] **Step 1: Write failing test that Help points to `.html` manual paths.**
- [ ] **Step 2: Create self-contained HTML manuals describing current LAN, backfill, station edit, alarm response, health, Grafana, and recovery workflows without embedding secrets.**
- [ ] **Step 3: Update Desktop Help to open local HTML files in default browser and preserve explicit failure feedback.**
- [ ] **Step 4: Audit visible controls touched by this change; disable unsupported LAN hardware identity editing rather than leaving a deceptive writable field.**
- [ ] **Step 5: Run focused tests and commit.**

### Task 8: Integration regression and release to main

**Files:**
- Modify tests/docs only as required by verified behavior.

**Interfaces:**
- Final branch must be fast-forwardable from the approved `main` base.

- [ ] **Step 1: Run the complete pytest suite in CI on the exact implementation branch HEAD.**
- [ ] **Step 2: Run compile validation and Grafana payload validation on the exact HEAD.**
- [ ] **Step 3: Inspect failures; fix implementation defects rather than weakening tests.**
- [ ] **Step 4: Re-run exact-HEAD CI until all checks pass.**
- [ ] **Step 5: Confirm `main` has not advanced unexpectedly; fast-forward `main` to the verified implementation HEAD.**
- [ ] **Step 6: Verify CI/status on the exact `main` SHA and report the SHA plus any LAN-only verification that CI cannot perform.**
