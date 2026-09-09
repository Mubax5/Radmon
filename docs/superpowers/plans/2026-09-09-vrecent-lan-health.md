# VRecent LAN Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PC 192.168.1.2 poll the three production `ipradmon` databases every 2 seconds, mirror authoritative `vrecent`/`recent` live state and legacy alarms, keep `measurement` for history, and notify operators when a source becomes unavailable or recovers.

**Architecture:** Each LAN source cycle prioritizes a lightweight live snapshot read from `vrecent` and incremental alarm read before one bounded history batch per detector. Central `vrecent` becomes the read model for Admin/Grafana live monitoring, while `measurement` remains history/trend/report storage. Source health state is stored in the security sidecar and surfaced through Admin/API without modifying source schemas.

**Tech Stack:** Python 3, MariaDB 10.x-compatible SQL, PySide6, FastAPI, Grafana JSON generation, SQLite security sidecar, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-vrecent-lan-health-design.md`

## Global Constraints

- Database name remains exactly `ipradmon`.
- LAN source cadence defaults to exactly 2 seconds.
- `vrecent` is required for live monitoring and `recent` remains populated.
- `measurement` remains historical storage and trend/report/archive source.
- Source writes are forbidden except explicit ACK/Response.
- Source failures are isolated; healthy sources continue polling.
- Production legacy alarm identity is `serid + dtoa`.
- Production station identities include `3003` R. Sementasi and `5501` PSLAT.

---

### Task 1: Production schema and station contract

**Files:**
- Modify: `radmon/repository.py`
- Modify: `radmon/stations.py`
- Test: `tests/test_repository.py`
- Test: `tests/test_stations.py`

**Interfaces:**
- Produces: schema validation accepting production `alarm/applog/news/rawdata` columns and requiring `vrecent` view columns.
- Produces: fallback catalog using `3003` and `5501`.

- [ ] Write failing tests that assert production schema names and corrected station IDs.
- [ ] Run focused tests and confirm they fail for current expectations.
- [ ] Update schema contract and station catalog.
- [ ] Re-run focused tests and confirm pass.

### Task 2: VRecent live repository path

**Files:**
- Modify: `radmon/repository.py`
- Modify: `radmon/admin/recent_page.py`
- Test: `tests/test_repository.py`
- Test: `tests/test_admin_ui_v3.py`

**Interfaces:**
- Produces: `MariaDBRepository.latest_reading()` reading `vrecent`.
- Produces: `MariaDBRepository.live_rows()` returning all current station snapshot/aggregate fields.
- Consumes: `vrecent` production contract from Task 1.

- [ ] Add failing tests proving live reads use `vrecent` and return aggregate fields without 10-minute history scans.
- [ ] Run focused tests and verify expected failure.
- [ ] Implement `live_rows()` and route `latest_reading()` through `vrecent`.
- [ ] Update Recent page to render `avgrate` and `dose` from `live_rows()`.
- [ ] Re-run focused tests and confirm pass.

### Task 3: LAN live snapshot and bounded history pull

**Files:**
- Modify: `radmon/lan.py`
- Test: `tests/test_lan.py`

**Interfaces:**
- Produces: `RemoteMariaDBSource.live_rows() -> list[dict]` selecting `vrecent`.
- Produces: `MariaCentralStore.upsert_live_rows(source_id, rows) -> int` updating `device` and full `recent` snapshots.
- Changes: `LanAggregator.run_source_once()` performs live/alarm first and at most one history batch per station per cycle.

- [ ] Add failing tests that live snapshot is upserted before history and history is bounded to one batch.
- [ ] Run focused tests and confirm failure.
- [ ] Implement remote `vrecent` read and central `device/recent` upsert.
- [ ] Reorder/bound source cycle.
- [ ] Re-run focused tests and confirm pass.

### Task 4: Incremental legacy alarm polling

**Files:**
- Modify: `radmon/security.py`
- Modify: `radmon/lan.py`
- Modify: `radmon/remote_alarm.py`
- Test: `tests/test_lan.py`
- Test: `tests/test_remote_alarm.py`

**Interfaces:**
- Produces: per-source alarm checkpoint `(dtoa, serid)` in SQLite.
- Produces: `RemoteMariaDBSource.alarms_after(checkpoint, limit)` using production legacy alarm columns.
- Changes: central alarm persistence uses production legacy schema.

- [ ] Add failing tests for alarm checkpoint ordering, legacy central insert, and no repeated full-table polling.
- [ ] Verify RED.
- [ ] Implement checkpoint storage and incremental query.
- [ ] Mirror legacy alarm columns into central `alarm` with idempotency on `(dtoa, serid)`.
- [ ] Verify GREEN.

### Task 5: Source health monitor and notifications

**Files:**
- Modify: `radmon/security.py`
- Create: `radmon/source_health.py`
- Modify: `radmon/lan_runtime.py`
- Modify: `radmon/secure_context.py`
- Modify: `radmon/secure_api.py`
- Test: `tests/test_source_health.py`

**Interfaces:**
- Produces: `SourceHealthService.record_success(source, ...)` and `record_failure(source, error)`.
- Produces: `SourceHealthService.list_states()`.
- Produces API: `GET /api/v1/control/sources/health`.
- Admin Recent Message panel receives state-transition messages.

- [ ] Add failing tests for CONNECTED -> DEGRADED -> OFFLINE -> RECOVERED transition and transition-only messages.
- [ ] Verify RED.
- [ ] Add sidecar table/service and runtime integration.
- [ ] Expose health endpoint and Recent messages.
- [ ] Verify GREEN.

### Task 6: Grafana realtime uses VRecent

**Files:**
- Modify: `radmon/grafana_tv.py`
- Modify: `radmon/grafana_revision.py`
- Test: `tests/test_grafana_tv.py`
- Test: `tests/test_grafana_revision.py`

**Interfaces:**
- Live/status/current summary panels select from `vrecent`.
- Historical sparkline and 3-hour trend panels continue selecting `measurement`.
- Alarm table selects legacy `dtoa/lvl/mvalue/thvalue/nhit/i_op/pic/note`.

- [ ] Add failing SQL-contract tests.
- [ ] Verify RED.
- [ ] Replace realtime/status SQL with `vrecent`, preserve historical measurement SQL, and update alarm SQL.
- [ ] Verify GREEN.

### Task 7: Production applog/rawdata compatibility and docs

**Files:**
- Modify: `radmon/application_log.py`
- Modify: `radmon/repository.py`
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/test_audit.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- `applog` writes `(ts, id, msg)`.
- local raw acquisition writes `(serid, dtom, val)`.
- docs explain source `.50/.52/.38`, central PC `.2`, 2-second polling, `vrecent` live model, and health notifications.

- [ ] Add failing production-schema SQL tests.
- [ ] Verify RED.
- [ ] Update SQL and documentation.
- [ ] Verify GREEN.

### Task 8: Full verification and main promotion

**Files:**
- No new production files unless a verification failure reveals a defect.

- [ ] Run full pytest suite.
- [ ] Run `python -m compileall -q .`.
- [ ] Generate/validate Grafana payloads using existing test suite.
- [ ] Confirm no credentials were committed.
- [ ] Confirm temp branch is a fast-forward descendant of current `main`.
- [ ] Move `main` to the verified temp-branch HEAD.
- [ ] Confirm GitHub Actions on the resulting main HEAD succeeds before reporting completion.
