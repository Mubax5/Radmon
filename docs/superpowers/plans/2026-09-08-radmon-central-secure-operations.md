# RadMon Secure Central Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build LAN central aggregation, multi-user auth/PIN/audit, legacy alarm ACK/Response, web-ready protected control endpoints, optional WhatsApp notification, and the requested Grafana fixes while preserving the existing RadMon detector/dummy workflows.

**Architecture:** Production building databases remain unchanged. PC3 pulls full history incrementally into central `ipradmon`; security/session/audit/source state live in a local SQLite sidecar. Protected business services are UI-independent and shared by PySide6 and FastAPI. Alarm ACK writes through to the source legacy DB first and only then updates local control state/audit.

**Tech Stack:** Python 3.12, MariaDB, SQLite stdlib, PySide6, FastAPI/Pydantic, PyQtGraph, Grafana 13.1.3, optional Selenium WhatsApp sender, pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-radmon-central-secure-operations-design.md`

## Global Constraints

- Preserve existing production `ipradmon` source schemas; no source migration.
- Keep `measurement` as the realtime/history source of truth.
- Keep detector acquisition and Admin refresh target at 2 seconds.
- Keep Grafana at 3 logical pages, 5 Operations variants, 7 dashboards, 15 playlist items, 10s playlist interval, 2s refresh, and grid bottom <= 24.
- No hardware alarm silence command in this revision.
- No committed production DB password, user password, PIN, browser profile, or session token.
- Sensitive writes require backend role authorization and current-user PIN validation.
- Every mutating/security action is structured-audited; concise safe summaries also go to `applog`.
- Remote Git branch list must remain `main` only.

---

### Task 1: Fix Grafana timestamps and shared WIB header

**Files:**
- Modify: `radmon/grafana_tv.py`
- Modify: `tests/test_grafana_tv.py`
- Modify: `tests/test_grafana_monitoring.py`

**Interfaces:**
- Produces: `_time_stat()` numeric epoch-millisecond query with `dateTimeAsLocal`.
- Produces: `_header_panels()` containing title plus left date, center organization, right update-time panels without changing center organization font sizing.

- [ ] **Step 1: Write failing Grafana tests**
  - Assert detector time SQL contains `UNIX_TIMESTAMP(MAX(m.dtom)) * 1000` and not `DATE_FORMAT`.
  - Assert unit is `dateTimeAsLocal`.
  - Assert each generated dashboard exposes left header date, unchanged center organization HTML/font clamp, and right update time.
  - Assert max grid bottom remains <= 24.

- [ ] **Step 2: Verify RED in CI**
  - Push tests only and confirm GitHub Actions fails on the old `DATE_FORMAT` behavior/header contract.

- [ ] **Step 3: Implement minimal Grafana change**
  - Restore numeric timestamp query.
  - Split organization row into 3 aligned text/stat panels using MariaDB `CONVERT_TZ(NOW(), '+00:00', '+07:00')`/formatting or equivalent explicit WIB calculation.
  - Keep center typography exactly at the existing `clamp(13px,.95vw,18px);font-weight:650`.

- [ ] **Step 4: Verify GREEN**
  - Confirm targeted Grafana tests and payload validation pass.

### Task 2: Add security store, roles, password/PIN hashing, sessions

**Files:**
- Create: `radmon/security.py`
- Create: `tests/test_security.py`
- Modify: `radmon/config.py`
- Modify: `.env.example`

**Interfaces:**
- `Role(str, Enum)`: `ADMINISTRATOR`, `OPERATOR`, `VIEWER`.
- `UserIdentity`: immutable username/display_name/role.
- `SecurityStore(path: Path)`.
- `create_user(username, display_name, role, password, pin, actor=None)`.
- `authenticate(username, password) -> UserIdentity | None`.
- `verify_pin(username, pin) -> bool`.
- `create_session(username, ttl_seconds) -> str`.
- `session_user(token) -> UserIdentity | None`.
- `revoke_session(token)`.
- `require_role(identity, *roles)`.

- [ ] **Step 1: Add failing tests** for salted PBKDF2 password/PIN hashes, role matrix, disabled accounts, expiring opaque sessions, bootstrap user creation, and no plaintext secret persistence.
- [ ] **Step 2: Verify RED** via CI.
- [ ] **Step 3: Implement SQLite schema and service** using `hashlib.pbkdf2_hmac`, `secrets`, constant-time comparison, UTC timestamps, WAL mode, and transaction boundaries.
- [ ] **Step 4: Verify GREEN**.

### Task 3: Add structured audit and applog bridge

**Files:**
- Create: `radmon/audit.py`
- Create: `tests/test_audit.py`
- Modify: `radmon/repository.py`

**Interfaces:**
- `AuditEvent` dataclass.
- `AuditTrail(SecurityStore, application_logger)`.
- `record(action, identity, target_type, target_id, before=None, after=None, success=True, reason=None, source=None)`.
- Repository `record_applog(message, at=None)`.

- [ ] **Step 1: Add failing tests** asserting before/after serialization, username/role/action/result persistence, and redaction of keys matching password/pin/token/secret/database password.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement audit persistence and concise `applog` bridge**.
- [ ] **Step 4: Verify GREEN**.

### Task 4: Add LAN source parser, schema detection, incremental full-history aggregation

**Files:**
- Create: `radmon/lan.py`
- Create: `tests/test_lan.py`
- Modify: `radmon/config.py`
- Modify: `radmon/repository.py`
- Modify: `.env.example`

**Interfaces:**
- `LanSource(source_id, host, port, database, user, password)`.
- `parse_lan_sources(settings) -> list[LanSource]`.
- `RemoteSchema(kind: 'legacy'|'current', ...)`.
- `LanSourceRepository` for remote read/write.
- `LanCheckpointStore` per source/station.
- `LanAggregator.run_source_once(source) -> PullResult`.
- Central repository `import_measurements(rows)` preserving remote `dose` and ignoring duplicate `(serid, dtom)`.

- [ ] **Step 1: Add failing tests** for three-source parsing, legacy/current schema detection, independent source failures, checkpoints, duplicate suppression, dose preservation, device insert-without-overwrite, and outage behavior.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement adapters and aggregator** with one worker per source and bounded retry.
- [ ] **Step 4: Verify GREEN**.

### Task 5: Mirror legacy alarms and implement PIN-gated ACK write-through

**Files:**
- Create: `radmon/remote_alarm.py`
- Create: `tests/test_remote_alarm.py`
- Modify: `radmon/lan.py`
- Modify: `radmon/repository.py`

**Interfaces:**
- `RemoteAlarm` with source_id, serid, event_time, level, measured_value, threshold, hit_count, acknowledged_at, pic, action, note.
- `RemoteAlarmStore` sidecar methods for mirror/query.
- `AlarmControlService.ack(identity, pin, alarm_key, action, pic, note) -> RemoteAlarm`.

- [ ] **Step 1: Add failing tests** proving legacy key is `(serid, dtoa)`, update includes `i_op IS NULL`, Action/PIC/Note are written, duplicate ACK is rejected, source failure never marks local alarm acknowledged, and successful ACK audits exact safe before/after state.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement mirror and control service**; map legacy `lvl=1` to ALERT and `lvl=2` to ALARM.
- [ ] **Step 4: Verify GREEN**.

### Task 6: Add protected station/device updates including safe central SERID migration

**Files:**
- Modify: `radmon/repository.py`
- Create: `radmon/device_admin.py`
- Create: `tests/test_device_admin.py`

**Interfaces:**
- `DeviceAdminService.update_station(identity, pin, serid, changes)`.
- Administrator-only validation.
- Allowed normal fields: name/location/description/warnlevel/alarmlevel/maxidlemin/unit.
- Dedicated `migrate_serid(identity, pin, old_serid, new_serid)` for central references.

- [ ] **Step 1: Add failing tests** for role denial, PIN denial, allowed field validation, thresholds, uniqueness, transactional reference migration, and audit before/after.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement minimal service/repository operations** without changing remote source SERID automatically.
- [ ] **Step 4: Verify GREEN**.

### Task 7: Add secure web-ready control API

**Files:**
- Modify: `radmon/central_api.py`
- Create: `tests/test_central_security_api.py`

**Interfaces:**
- `POST /auth/login` -> HttpOnly session cookie.
- `POST /auth/logout`.
- `GET /auth/me`.
- Protected `GET /api/v1/alarms`.
- Protected PIN-gated `POST /api/v1/alarms/{source_id}/{serid}/ack`.
- Administrator PIN-gated station/user management endpoints.
- Existing bearer-token ingestion endpoints remain available to SyncAgent and are not replaced by browser sessions.

- [ ] **Step 1: Add failing FastAPI tests** for anonymous rejection, session login, role enforcement, PIN enforcement, logout, and ingestion bearer-token compatibility.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement session dependencies and service calls** with HttpOnly/SameSite cookies; keep TLS deployment as documented requirement.
- [ ] **Step 4: Verify GREEN**.

### Task 8: Upgrade PySide6 Admin login, role UI, active alarm strip, ACK/Response and admin dialogs

**Files:**
- Create: `radmon/admin/auth_dialogs.py`
- Create: `radmon/admin/alarm_response_dialog.py`
- Create: `radmon/admin/user_admin_dialog.py`
- Create: `radmon/admin/station_admin_dialog.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `main.py`
- Create/Modify: Qt tests under `tests/`

**Interfaces:**
- Login must succeed before MainWindow construction.
- MainWindow receives `identity`, `security_store`, `alarm_control`, `device_admin`.
- Active alarm strip at window bottom shows newest active ALERT/ALARM and response state.
- Operator/Admin ACK opens Action/PIC/Note then PIN prompt.
- Admin user/station mutations require PIN and backend service authorization.

- [ ] **Step 1: Add failing offscreen Qt tests** for login gate, role-aware actions, active alarm strip, ACK dialog/service call, PIN cancel/failure, user admin visibility, station edit permissions, and icon resolution.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement focused dialogs and MainWindow wiring**.
- [ ] **Step 4: Verify GREEN**.

### Task 9: Add LAN runner/runtime integration and optional WhatsApp dispatcher

**Files:**
- Create: `RUN_LAN.bat`
- Modify: `main.py`
- Modify: `radmon/runtime.py`
- Create: `radmon/whatsapp.py`
- Create: `tests/test_whatsapp.py`
- Modify: `.env.example`
- Modify: `requirements.txt` only if Selenium runtime support is committed.

**Interfaces:**
- `main.py --source detector|dummy|lan`.
- LAN source starts aggregator workers but no local detector/dummy acquisition.
- `WhatsAppAlarmDispatcher.run_once()` reads central mirrored new alarms and uses injected sender.
- Selenium sender is lazy/optional and disabled by default.

- [ ] **Step 1: Add failing tests** for LAN runtime thread selection, no detector acquisition in LAN mode, deduplicated WA notification state, retry on send failure, and disabled-by-default behavior.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement runtime/launcher/dispatcher**.
- [ ] **Step 4: Verify GREEN**.

### Task 10: Documentation, CI contract and final verification

**Files:**
- Modify: `README.md`
- Modify: `grafana/README.md`
- Modify: `.github/workflows/ci.yml` if needed only to validate new deterministic contracts.

**Interfaces:** Documentation becomes consistent with code: five Operations variants, epoch Grafana detector time formatting, LAN topology, auth roles, PIN behavior, URL security requirements, runners, and environment variables.

- [ ] **Step 1: Update docs** with no production credentials.
- [ ] **Step 2: Run/observe full GitHub Actions**: pytest, compile, Grafana payload/YAML validation.
- [ ] **Step 3: Inspect failed checks using systematic debugging and fix root causes** until HEAD is green.
- [ ] **Step 4: Compare final HEAD against implementation start** and review changed files for accidental secrets/legacy passwords.
- [ ] **Step 5: Verify GitHub remote branches contain only `main`**.
- [ ] **Step 6: Report exact changed behavior and final HEAD/CI result.**
