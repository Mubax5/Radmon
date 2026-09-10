# RadMon Production Integration Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC3 station editing, PIN security, LAN live/history ingestion, alarm response, offline recovery, Grafana charts, refresh, and HTML manuals work end-to-end against production `ipradmon` sources.

**Architecture:** Preserve the current central-server ownership and split live/backfill workers. Add source-aware write-through services and an in-memory sensitive-operation lease; keep `vrecent` authoritative for live state and `measurement` authoritative for history/charts. Update the desktop tree and Grafana queries to consume live database metadata rather than frozen UI/catalog values.

**Tech Stack:** Python 3.14, MariaDB connector, PySide6, FastAPI/Uvicorn, SQLite security sidecar, Grafana JSON generator, pytest, GitHub Actions.

**Spec:** `docs/2026-09-10-production-integration-fix-design.md`

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

**Files:** `radmon/security.py`, `radmon/admin/auth_dialogs.py`, station/alarm/user dialogs, `radmon/secure_context.py`, security tests.

- [ ] Write failing lease tests for grant, reuse, expiry, invalid PIN, role enforcement, and clear.
- [ ] Verify RED in CI.
- [ ] Implement in-memory 600-second lease with role checks on every call and clear on logout/disable/revoke.
- [ ] Make sensitive UI prompts lease-aware.
- [ ] Verify focused/full tests.

### Task 2: Source-aware Station Properties write-through

**Files:** `radmon/security.py`, `radmon/lan_revision.py`, `radmon/device_admin.py`, `radmon/secure_services.py`, `radmon/admin/station_admin_dialog.py`, tests.

- [ ] Write failing tests that source is updated before central and source failure leaves central unchanged.
- [ ] Test LAN hardware identity fields are not writable.
- [ ] Implement central-SERID to source/remote-SERID lookup and source `device` update/readback.
- [ ] Wire LAN DeviceAdmin to write-through while preserving non-LAN behavior.
- [ ] Disable LAN SERID/hardware identity editing.
- [ ] Verify tests.

### Task 3: Live sample insertion for immediate charts

**Files:** `radmon/lan_revision.py`, LAN/vrecent tests.

- [ ] Write failing test that live `vrecent` inserts current sample into central `measurement` exactly once.
- [ ] Verify RED.
- [ ] Implement idempotent live measurement insert while keeping historical backfill from changing `recent`.
- [ ] Verify tests.

### Task 4: Production alarm `i_flag` synchronization and one-step response

**Files:** `radmon/lan_revision.py`, `radmon/remote_alarm.py`, `radmon/remote_alarm_revision.py`, Alarm UI, tests.

- [ ] Write failing SQL/service tests for `i_flag=1`, preserved `ack`, and source-first behavior.
- [ ] Write failing mirror test that `active_only` follows `i_flag` even if `i_op` is absent.
- [ ] Verify RED.
- [ ] Add active-alarm refresh each live cycle plus incremental alarm history.
- [ ] Implement one-step response with Action/PIC/Note and central mirror update after source success.
- [ ] Verify tests.

### Task 5: Three collapsible source parents and complete Refresh

**Files:** `radmon/admin/main_window.py`, `radmon/secure_context.py`, `radmon/security.py`, tests.

- [ ] Add tested pure grouping helper using source mappings, not SERID ranges.
- [ ] Implement collapsible parent nodes with host and source state.
- [ ] Preserve expanded/collapsed state on reload.
- [ ] Make F5/manual Refresh reload hierarchy, health, selected details, messages/alarm, and current page.
- [ ] Keep automatic 2-second refresh lightweight.

### Task 6: Offline recovery and database-driven Grafana

**Files:** `radmon/grafana_revision.py`, Grafana/status tests.

- [ ] Verify status SQL uses fresh `vrecent.dtom` and database threshold columns.
- [ ] Remove stale catalog threshold coloring where it conflicts with editable DB thresholds.
- [ ] Keep trends/sparklines on `measurement`, which now receives current points from Task 3.
- [ ] Verify stale->OFFLINE then fresh->NORMAL/ALERT/ALARM behavior is non-sticky.

### Task 7: Browser HTML manuals and non-placeholder controls

**Files:** create `docs/manual/installation.html`, `docs/manual/user-manual.html`, `docs/manual/manual.css`; modify `radmon/admin/main_window.py`; tests.

- [ ] Write failing manual-path test.
- [ ] Create HTML manuals for current deployment and operations without secrets.
- [ ] Open manuals in browser through local file URLs and explicit failure feedback.
- [ ] Disable unsupported LAN hardware identity editing instead of presenting it as functional.

### Task 8: Integration regression and release to main

- [ ] Run complete CI on exact implementation HEAD.
- [ ] Verify pytest, compileall, and Grafana payload validation.
- [ ] Fix implementation defects, not tests, until green.
- [ ] Confirm `main` has not advanced unexpectedly.
- [ ] Fast-forward `main` to verified HEAD.
- [ ] Verify exact `main` SHA and report LAN-only checks that CI cannot perform.
