# RadMon Alarm Policy and Suppression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a restart-safe central alarm policy with a three-trigger rolling-five-minute rule, timed per-detector suppression, strict one-event suppression anti-spam, authenticated control, Grafana projection, and notification idempotency without changing any production source schema.

**Architecture:** Canonical policy state lives in the existing central SQLite security/runtime database. `AlarmPolicyStore` owns additive migrations and transactions; `AlarmPolicyService` owns threshold/retrigger decisions; `AlarmSuppressionService` owns timed suppression; existing source alarm rows remain raw evidence in `RemoteAlarmMirror`; `AlarmControlService` performs source write-through; `RuntimeStatusProjector` publishes current policy state to a central-only MariaDB table for Grafana. The LAN live cycle feeds mapped `vrecent` rows and newly mirrored source alarm rows into the policy service after raw mirroring, while historical seed rows are marked non-notifying.

**Tech Stack:** Python 3.12, SQLite, MariaDB Connector/Python, PySide6, FastAPI/Pydantic, Grafana dashboard JSON builders, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-alarm-policy-suppression-icon-system-design.md`

## Global Constraints

- Target branch is `main`; do not create permanent feature branches.
- Do not migrate or add tables/columns on source MariaDB hosts `192.168.1.50`, `192.168.1.52`, or `192.168.1.38`.
- Source alarm response remains: set `i_op`, `pic`, `note`, transition `i_flag 0 -> 1`, preserve `ack`.
- `NORMAL` for policy reset means dose `< LOW/WARN`; `ALERT` does not reset the episode.
- A burst surfaces at most three ALARMs. The five-minute window is anchored to #1; `<= 5 minutes` remains in the burst, `> 5 minutes` starts a new burst if #3 was not reached.
- ALARM #3 immediately sets `RETRIGGER_LOCKED`; only a later NORMAL reading clears that lock.
- Suppression is per detector, requires PIN + PIC + reason + duration, and duration is `60..86400` seconds. No indefinite suppression.
- If a suppression session sees no HIGH, it creates zero SUPPRESSED policy events. If it sees one or more HIGH states/events, it creates exactly one SUPPRESSED policy event for that detector/session.
- SUPPRESSED never hides actual dose or the underlying NORMAL/ALERT/ALARM condition.
- Administrator and Operator may suppress; Viewer may only view.
- Explicitly supplied wrong PIN remains invalid even when a short sensitive-operation lease exists.
- Historical/backfill alarm seed rows never become new notifications.
- Existing Grafana WIB conversion, 2-second refresh, playlist behavior, source health isolation, archive behavior, and LIVE/backfill behavior must remain intact.

---

## File Map

- Create `radmon/alarm_policy_store.py`: SQLite schema, dataclasses, transactional CRUD, idempotency/uniqueness guards.
- Create `radmon/alarm_policy.py`: threshold/retrigger state machine and policy-event decisions.
- Create `radmon/alarm_suppression.py`: timed suppression lifecycle and validation.
- Create `radmon/runtime_status.py`: central-only MariaDB `radmon_runtime_status` projection.
- Create `radmon/alarm_policy_revision.py`: narrow glue applied after current production/safety patches; raw mirror annotations, source-silence retry helpers, LAN cycle integration.
- Create `radmon/grafana_policy_revision.py`: Grafana policy JOIN/status display applied after WIB revision.
- Create `radmon/admin/suppression_dialog.py`: timed suppression form.
- Modify `radmon/security.py`: add `suppress_alarm` permission and base schema compatibility only where needed.
- Modify `radmon/secure_services.py`: construct/store new services and projector.
- Modify `radmon/secure_context.py`: expose policy/suppression services and render policy alarm strip.
- Modify `radmon/secure_api.py`: add policy event/suppression endpoints.
- Modify `radmon/lan_revision.py`: invoke attached policy processor with mapped live/alarm rows.
- Modify `radmon/lan_runtime.py`: attach policy processor to each aggregator and run bounded silence retries.
- Modify `radmon/whatsapp.py`: dispatch only policy ALARM events, once each.
- Modify `radmon/admin/alarm_page.py`: policy-filtered rows, response-by-policy-event, suppression button/status.
- Modify `radmon/admin/recent_page.py`: render prominent SUPPRESSED/underlying-dose state.
- Modify `radmon/admin/main_window.py`: selected-station suppression action and status/details refresh.
- Modify `main.py`: put new services into `SecurityContext`.
- Modify `central_server.py`: startup migration/projection ordering and API wiring.
- Modify `radmon/__init__.py`: apply alarm-policy revision and Grafana policy revision in safe order.
- Tests: `tests/test_alarm_policy_store.py`, `tests/test_alarm_policy.py`, `tests/test_alarm_suppression.py`, `tests/test_alarm_policy_integration.py`, `tests/test_alarm_policy_api.py`, `tests/test_alarm_suppression_ui.py`, `tests/test_runtime_status_projection.py`, `tests/test_grafana_alarm_policy.py`, `tests/test_alarm_policy_notifications.py`, plus existing regression tests.

---

### Task 1: Add the persistent alarm-policy store and additive SQLite migration

**Files:**
- Create: `radmon/alarm_policy_store.py`
- Test: `tests/test_alarm_policy_store.py`

**Interfaces:**
- Produces: `AlarmPolicyStore(security_store: SecurityStore)`
- Produces: `PolicyState`, `SuppressionRecord`, `PolicyEvent` dataclasses.
- Produces: `get_state(serid)`, `active_suppression(serid)`, `start_suppression(...)`, `end_suppression(...)`, `create_policy_event(...)`, `respond_event(...)`, `list_policy_events(...)`, `annotate_raw_alarm(...)`, `pending_source_silences(...)`.
- Later tasks depend on deterministic event keys and SQLite transactions from this store.

- [ ] **Step 1: Write failing migration/idempotency tests**

```python
# tests/test_alarm_policy_store.py
from datetime import datetime, timedelta
import sqlite3
import pytest
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.security import SecurityStore


def test_policy_schema_is_additive_and_idempotent(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    store.ensure_schema()
    store.ensure_schema()
    with security._connection() as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"alarm_policy_state", "alarm_suppression", "alarm_policy_event"} <= names


def test_one_active_suppression_per_detector_is_persistence_enforced(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    now = datetime(2026, 9, 11, 10, 0, 0)
    store.start_suppression(5201, now, now + timedelta(minutes=15), True, "PIC A", "Calibration", "op")
    with pytest.raises(sqlite3.IntegrityError):
        store.start_suppression(5201, now, now + timedelta(minutes=30), False, "PIC B", "Maintenance", "op")


def test_only_one_suppressed_event_can_exist_per_suppression(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    now = datetime(2026, 9, 11, 10, 0, 0)
    suppression = store.start_suppression(5201, now, now + timedelta(minutes=15), True, "PIC A", "Calibration", "op")
    first = store.create_policy_event(
        event_key=f"suppressed:{suppression.suppression_id}", serid=5201,
        kind="SUPPRESSED", origin="central_policy", surfaced_at=now,
        measured_value=160.0, threshold=150.0,
        suppression_id=suppression.suppression_id, status="AUTO_SILENCED",
    )
    second = store.create_policy_event(
        event_key=f"suppressed:{suppression.suppression_id}", serid=5201,
        kind="SUPPRESSED", origin="central_policy", surfaced_at=now,
        measured_value=170.0, threshold=150.0,
        suppression_id=suppression.suppression_id, status="AUTO_SILENCED",
    )
    assert second.event_id == first.event_id
    assert len(store.list_policy_events(serid=5201)) == 1
```

- [ ] **Step 2: Run the new store tests and verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_store.py`
Expected: FAIL because `radmon.alarm_policy_store` does not exist.

- [ ] **Step 3: Implement the schema and core transaction methods**

Use this schema verbatim as the first migration in `AlarmPolicyStore.ensure_schema()`:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS alarm_policy_state (
  serid INTEGER PRIMARY KEY,
  window_started_at TEXT,
  trigger_count INTEGER NOT NULL DEFAULT 0 CHECK(trigger_count BETWEEN 0 AND 3),
  retrigger_locked INTEGER NOT NULL DEFAULT 0 CHECK(retrigger_locked IN (0, 1)),
  active_event_id TEXT,
  last_trigger_at TEXT,
  last_normal_at TEXT,
  updated_at TEXT NOT NULL,
  CHECK(retrigger_locked = 0 OR trigger_count = 3)
);
CREATE TABLE IF NOT EXISTS alarm_suppression (
  suppression_id TEXT PRIMARY KEY,
  serid INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  auto_resume_on_normal INTEGER NOT NULL CHECK(auto_resume_on_normal IN (0, 1)),
  pic TEXT NOT NULL,
  reason TEXT NOT NULL,
  started_by TEXT NOT NULL,
  ended_at TEXT,
  ended_reason TEXT,
  first_suppressed_alarm_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alarm_suppression_active_serid
ON alarm_suppression(serid) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS alarm_policy_event (
  event_id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  serid INTEGER NOT NULL,
  source_id TEXT,
  remote_serid INTEGER,
  remote_event_time TEXT,
  origin TEXT NOT NULL,
  kind TEXT NOT NULL,
  trigger_index INTEGER,
  surfaced_at TEXT NOT NULL,
  measured_value REAL,
  threshold REAL,
  status TEXT NOT NULL,
  suppression_id TEXT,
  responded_at TEXT,
  pic TEXT,
  action TEXT,
  reason TEXT,
  notification_sent_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alarm_policy_one_suppressed_per_session
ON alarm_policy_event(suppression_id)
WHERE kind = 'SUPPRESSED' AND suppression_id IS NOT NULL;
"""
```

Implement deterministic UUIDs from `event_key` using `uuid.uuid5(uuid.NAMESPACE_URL, f"radmon:{event_key}")`, ISO-8601 datetime serialization, `BEGIN IMMEDIATE` for state-changing transactions, and `INSERT ... ON CONFLICT(event_key) DO NOTHING` followed by a read-back so repeated evaluation is idempotent.

Also add raw mirror metadata columns additively in `ensure_schema()` using `PRAGMA table_info(remote_alarm_state)` before `ALTER TABLE`:

```text
policy_decision TEXT
suppression_id TEXT
operator_visible INTEGER NOT NULL DEFAULT 0
policy_event_id TEXT
source_silence_state TEXT
source_silence_retry_at TEXT
```

- [ ] **Step 4: Run store tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_store.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/alarm_policy_store.py tests/test_alarm_policy_store.py
git commit -m "feat: add persistent alarm policy store"
```

---

### Task 2: Implement the three-trigger rolling-five-minute policy state machine

**Files:**
- Create: `radmon/alarm_policy.py`
- Test: `tests/test_alarm_policy.py`

**Interfaces:**
- Consumes: `AlarmPolicyStore` from Task 1.
- Produces: `AlarmPolicyService(store, audit, now=None, projector=None)`.
- Produces: `process_cycle(source_id: str, live_rows: list[dict], alarm_rows: list[dict]) -> list[PolicyEvent]`.
- Produces: `evaluate_live(row: dict, *, source_id: str | None = None) -> dict`.
- Produces: `observe_source_alarm(source_id: str, row: dict) -> dict`.
- Produces: `get_policy(serid: int) -> dict` and `list_events(...)` for UI/API.

- [ ] **Step 1: Write failing boundary/retrigger tests**

```python
# tests/test_alarm_policy.py
from datetime import datetime, timedelta
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.security import SecurityStore


def row(at, dose):
    return {"serid": 5201, "dtom": at, "doserate": dose, "warnlevel": 100.0, "alarmlevel": 150.0}


def test_three_alarm_rule_and_normal_only_reset(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    service = AlarmPolicyService(store, AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)

    first = service.evaluate_live(row(t0, 151.0))
    assert first["policy_state"] == "ALARM"
    assert first["trigger_count"] == 1
    service.mark_event_responded(first["active_event_id"], t0 + timedelta(seconds=20), "PIC", "Confirm", "checked")

    second = service.evaluate_live(row(t0 + timedelta(minutes=3), 160.0))
    assert second["trigger_count"] == 2
    service.mark_event_responded(second["active_event_id"], t0 + timedelta(minutes=3, seconds=20), "PIC", "Confirm", "checked")

    third = service.evaluate_live(row(t0 + timedelta(minutes=4), 170.0))
    assert third["trigger_count"] == 3
    assert third["retrigger_locked"] is True
    service.mark_event_responded(third["active_event_id"], t0 + timedelta(minutes=4, seconds=20), "PIC", "Confirm", "checked")

    blocked = service.evaluate_live(row(t0 + timedelta(minutes=6), 180.0))
    assert blocked["trigger_count"] == 3
    assert blocked["retrigger_locked"] is True
    assert blocked["active_event_id"] is None

    alert = service.evaluate_live(row(t0 + timedelta(minutes=7), 120.0))
    assert alert["retrigger_locked"] is True

    normal = service.evaluate_live(row(t0 + timedelta(minutes=8), 99.0))
    assert normal["trigger_count"] == 0
    assert normal["retrigger_locked"] is False


def test_five_minute_window_is_anchored_to_first_alarm(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    service = AlarmPolicyService(AlarmPolicyStore(security), AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)
    a1 = service.evaluate_live(row(t0, 151.0))
    service.mark_event_responded(a1["active_event_id"], t0, "PIC", "Confirm", "x")
    a2 = service.evaluate_live(row(t0 + timedelta(minutes=3), 151.0))
    assert a2["trigger_count"] == 2
    service.mark_event_responded(a2["active_event_id"], t0, "PIC", "Confirm", "x")
    same_boundary = service.evaluate_live(row(t0 + timedelta(minutes=5), 151.0))
    assert same_boundary["trigger_count"] == 3


def test_after_window_next_alarm_is_new_one_when_not_locked(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    service = AlarmPolicyService(AlarmPolicyStore(security), AuditTrail(security))
    t0 = datetime(2026, 9, 11, 10, 0, 0)
    a1 = service.evaluate_live(row(t0, 151.0))
    service.mark_event_responded(a1["active_event_id"], t0, "PIC", "Confirm", "x")
    a2 = service.evaluate_live(row(t0 + timedelta(minutes=3), 151.0))
    service.mark_event_responded(a2["active_event_id"], t0, "PIC", "Confirm", "x")
    new_burst = service.evaluate_live(row(t0 + timedelta(minutes=7), 151.0))
    assert new_burst["trigger_count"] == 1
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy.py`
Expected: FAIL because the policy service is not implemented.

- [ ] **Step 3: Implement exact state transition rules**

Core transition skeleton in `AlarmPolicyService.evaluate_live()`:

```python
is_normal = dose_rate < warnlevel
is_alarm = dose_rate >= alarmlevel

with self.store.detector_transaction(serid) as tx:
    state = tx.state
    suppression = tx.active_suppression

    if is_normal:
        tx.reset_policy(measured_at)
        if suppression and suppression.auto_resume_on_normal:
            tx.end_suppression(suppression.suppression_id, measured_at, "AUTO_NORMAL")
        return tx.snapshot(underlying="NORMAL")

    if suppression:
        return self._evaluate_suppressed(tx, suppression, measured_at, dose_rate, alarmlevel)

    if not is_alarm:
        return tx.snapshot(underlying="ALERT")

    if state.retrigger_locked:
        tx.audit_decision("RETRIGGER_LOCKED")
        return tx.snapshot(underlying="ALARM")

    if state.active_event_id:
        tx.audit_decision("COALESCED_DUPLICATE")
        return tx.snapshot(underlying="ALARM")

    if state.window_started_at is None or measured_at - state.window_started_at > timedelta(minutes=5):
        state.window_started_at = measured_at
        state.trigger_count = 0

    next_index = state.trigger_count + 1
    event = tx.create_alarm_event(
        event_key=f"alarm:{serid}:{measured_at.isoformat()}:{next_index}",
        trigger_index=next_index,
        surfaced_at=measured_at,
        measured_value=dose_rate,
        threshold=alarmlevel,
    )
    state.trigger_count = next_index
    state.active_event_id = event.event_id
    state.last_trigger_at = measured_at
    if next_index == 3:
        state.retrigger_locked = True
    tx.save_state(state)
    return tx.snapshot(underlying="ALARM")
```

`observe_source_alarm()` must never increment counters by itself. It links a raw source row to the already-created policy event for the detector or classifies it as coalesced/suppressed/locked. Live current dose is the trigger authority so expiry-while-HIGH works without waiting for a source row.

`mark_event_responded()` updates the policy event status to `RESPONDED` and clears `active_event_id` only if it matches that event. It does not clear `retrigger_locked`.

- [ ] **Step 4: Run policy tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/alarm_policy.py tests/test_alarm_policy.py
git commit -m "feat: add rolling alarm policy state machine"
```

---

### Task 3: Implement timed suppression lifecycle and exact anti-spam behavior

**Files:**
- Create: `radmon/alarm_suppression.py`
- Test: `tests/test_alarm_suppression.py`

**Interfaces:**
- Consumes: `AlarmPolicyStore`, `AlarmPolicyService`, `SecurityStore`, `AuditTrail`.
- Produces: `AlarmSuppressionService(security, store, policy, audit, alarm_control=None, now=None)`.
- Produces: `start(identity, pin, serid, duration_seconds, pic, reason, auto_resume_on_normal) -> dict`.
- Produces: `list(active_only=False) -> list[dict]`.
- Policy service consumes the active suppression from the shared store on every live evaluation.

- [ ] **Step 1: Write suppression tests**

```python
# tests/test_alarm_suppression.py
from datetime import datetime, timedelta, timezone
import pytest
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.alarm_suppression import AlarmSuppressionService
from radmon.audit import AuditTrail
from radmon.security import Role, SecurityStore


def make(tmp_path):
    clock = [datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)]
    security = SecurityStore(tmp_path / "security.db", now=lambda: clock[0])
    security.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security), now=lambda: clock[0])
    service = AlarmSuppressionService(security, store, policy, AuditTrail(security), now=lambda: clock[0])
    return clock, security, store, policy, service


def test_suppression_requires_duration_pic_reason_and_permission(tmp_path):
    clock, security, store, policy, service = make(tmp_path)
    op = security.authenticate("op", "Password123!")
    with pytest.raises(ValueError):
        service.start(op, "1357", 5201, 59, "PIC", "Calibration", True)
    with pytest.raises(ValueError):
        service.start(op, "1357", 5201, 900, "", "Calibration", True)
    with pytest.raises(ValueError):
        service.start(op, "1357", 5201, 900, "PIC", "", True)


def test_suppression_creates_exactly_one_event_for_many_high_cycles(tmp_path):
    clock, security, store, policy, service = make(tmp_path)
    op = security.authenticate("op", "Password123!")
    session = service.start(op, "1357", 5201, 900, "PIC", "Calibration", True)
    for second in range(20):
        policy.evaluate_live({
            "serid": 5201, "dtom": clock[0] + timedelta(seconds=second),
            "doserate": 170.0, "warnlevel": 100.0, "alarmlevel": 150.0,
        })
    events = [e for e in store.list_policy_events(serid=5201) if e.kind == "SUPPRESSED"]
    assert len(events) == 1
    assert events[0].suppression_id == session["suppression_id"]
    assert store.get_state(5201).trigger_count == 0


def test_auto_resume_requires_actual_normal_not_alert(tmp_path):
    clock, security, store, policy, service = make(tmp_path)
    op = security.authenticate("op", "Password123!")
    service.start(op, "1357", 5201, 900, "PIC", "Calibration", True)
    policy.evaluate_live({"serid":5201,"dtom":clock[0],"doserate":120.0,"warnlevel":100.0,"alarmlevel":150.0})
    assert store.active_suppression(5201) is not None
    policy.evaluate_live({"serid":5201,"dtom":clock[0],"doserate":99.0,"warnlevel":100.0,"alarmlevel":150.0})
    assert store.active_suppression(5201) is None


def test_expiry_while_high_surfaces_fresh_one_unless_locked(tmp_path):
    clock, security, store, policy, service = make(tmp_path)
    op = security.authenticate("op", "Password123!")
    service.start(op, "1357", 5201, 60, "PIC", "Calibration", False)
    policy.evaluate_live({"serid":5201,"dtom":clock[0],"doserate":170.0,"warnlevel":100.0,"alarmlevel":150.0})
    clock[0] += timedelta(seconds=61)
    snap = policy.evaluate_live({"serid":5201,"dtom":clock[0],"doserate":170.0,"warnlevel":100.0,"alarmlevel":150.0})
    assert snap["policy_state"] == "ALARM"
    assert snap["trigger_count"] == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_suppression.py`
Expected: FAIL before service implementation.

- [ ] **Step 3: Implement validation and lifecycle**

Use exact permission and validation order:

```python
self.security.require_sensitive(identity, "suppress_alarm", pin)
if not 60 <= int(duration_seconds) <= 86400:
    raise ValueError("Durasi suppression harus 1 menit sampai 24 jam")
if not str(pic).strip():
    raise ValueError("PIC wajib diisi")
if not str(reason).strip():
    raise ValueError("Alasan suppression wajib diisi")
```

Before creating a non-locked suppression, clear `window_started_at`, `trigger_count`, `active_event_id`, and `last_trigger_at`. If state is already locked, preserve `trigger_count == 3` and `retrigger_locked == True`. If an active policy ALARM exists, call `alarm_control.respond_policy_event(..., action="Suppressed", pic=pic, reason=reason)`; a remote write failure must be recorded/pending but must not abort central suppression creation.

For suppressed HIGH, create exactly one deterministic event:

```python
event_key = f"suppressed:{suppression.suppression_id}"
```

Set status `AUTO_SILENCED`, set `first_suppressed_alarm_at` only once, do not increment trigger count, and do not set notification pending.

- [ ] **Step 4: Run suppression tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_suppression.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/alarm_suppression.py tests/test_alarm_suppression.py
git commit -m "feat: add timed alarm suppression"
```

---

### Task 4: Wire raw source alarms, policy decisions, responses, and bounded source-silence retry

**Files:**
- Create: `radmon/alarm_policy_revision.py`
- Modify: `radmon/lan_revision.py`
- Modify: `radmon/lan_runtime.py`
- Modify: `radmon/remote_alarm.py`
- Modify: `radmon/__init__.py`
- Test: `tests/test_alarm_policy_integration.py`

**Interfaces:**
- Consumes: policy/suppression/store from Tasks 1-3.
- Produces on `RemoteAlarmMirror`: `annotate_policy(...)`, `pending_source_silences(...)`, `mark_source_silence_result(...)`.
- Produces on `AlarmControlService`: `respond_policy_event(identity, pin, event_id, *, action, pic, reason)` and `silence_source_row(...)`.
- `LanAggregator` gets an optional runtime attribute `alarm_policy` set by `LanRuntime._aggregator()`.

- [ ] **Step 1: Write integration tests for raw-vs-visible separation and write-through semantics**

```python
# tests/test_alarm_policy_integration.py
from datetime import datetime, timedelta
from radmon.lan import LanSource, RemoteMariaDBSource


def test_source_silence_sql_sets_i_flag_and_preserves_ack():
    class Cursor:
        rowcount = 1
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()): self.sql, self.params = sql, params
    class Connection:
        def __init__(self): self.c = Cursor()
        def cursor(self): return self.c
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    db = Connection()
    remote = RemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: db,
    )
    remote.respond_alarm(5201, datetime(2026,9,11,10,0), action="Suppressed", pic="PIC", note="Calibration", at=datetime(2026,9,11,10,1))
    sql = " ".join(db.c.sql.lower().split())
    assert "i_flag = 1" in sql
    assert "ack =" not in sql


def test_lan_revision_calls_policy_after_mapping_raw_rows():
    import inspect
    from radmon.lan import LanAggregator
    source = inspect.getsource(LanAggregator.run_live_once)
    assert "alarm_policy" in source
    assert "process_cycle" in source
```

Add a functional fake-source test that feeds the same raw `dtoa` twice and asserts: one raw mirror row, one policy event, one notification candidate.

- [ ] **Step 2: Run integration tests and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_integration.py`
Expected: FAIL until the policy hooks exist.

- [ ] **Step 3: Attach policy processing to the existing mapped live cycle**

In the patched `run_live_once()` inside `radmon/lan_revision.py`, after raw alarms have been mirrored to SQLite/MariaDB and before saving the alarm checkpoint, call:

```python
policy = getattr(self, "alarm_policy", None)
if policy is not None:
    policy.process_cycle(source.source_id, mapped_live, mapped_alarms)
```

In `LanRuntime._aggregator()`:

```python
aggregator = LanAggregator(...)
aggregator.alarm_policy = getattr(self.services, "alarm_policy", None)
return aggregator
```

This keeps current source mapping/historical-seed behavior intact and ensures policy sees central SERIDs.

- [ ] **Step 4: Add source-silence retry with bounded backoff**

Store `source_silence_state` as `PENDING`, `CONFIRMED`, or `FAILED`, and `source_silence_retry_at` as ISO time. On suppression/locked/coalesced decisions that require source silence, call `RemoteMariaDBSource.respond_alarm()`. If it fails, record `FAILED`, audit `SUPPRESSION_SOURCE_SILENCE_FAILED`, and schedule the next retry with delays `5s, 15s, 30s, 60s` capped at 60 seconds. The retry loop runs from each live source thread after the normal live poll and processes at most 25 pending rows per cycle for that source.

- [ ] **Step 5: Apply the new revision after production safety patches**

In `radmon/__init__.py`, add after `production_safety_revision` and before Grafana revisions that depend on policy data:

```python
from .alarm_policy_revision import apply as _apply_alarm_policy_revision
_apply_alarm_policy_revision()
del _apply_alarm_policy_revision
```

Do not replace the current safety reconciliation wrapper; wrap the already-final runtime behavior.

- [ ] **Step 6: Run integration and existing production safety tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_integration.py tests/test_production_integration_fix.py tests/test_production_safety_guards.py tests/test_lan.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/alarm_policy_revision.py radmon/lan_revision.py radmon/lan_runtime.py radmon/remote_alarm.py radmon/__init__.py tests/test_alarm_policy_integration.py
git commit -m "feat: integrate alarm policy with LAN alarm flow"
```

---

### Task 5: Construct services, permissions, startup ordering, and central runtime projection

**Files:**
- Create: `radmon/runtime_status.py`
- Modify: `radmon/security.py`
- Modify: `radmon/secure_services.py`
- Modify: `central_server.py`
- Test: `tests/test_runtime_status_projection.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Produces: `RuntimeStatusProjector(settings)` with `ensure_schema()` and `project(snapshot: dict) -> None`.
- `SecureServices` gains `alarm_policy_store`, `alarm_policy`, `alarm_suppression`, `runtime_status_projector`.

- [ ] **Step 1: Add permission and projection tests**

```python
def test_suppress_alarm_permission_matrix(tmp_path):
    from radmon.security import Role, SecurityStore
    store = SecurityStore(tmp_path / "security.db")
    assert store.role_allows(Role.ADMINISTRATOR, "suppress_alarm")
    assert store.role_allows(Role.OPERATOR, "suppress_alarm")
    assert not store.role_allows(Role.VIEWER, "suppress_alarm")
```

```python
# tests/test_runtime_status_projection.py
from radmon.runtime_status import RuntimeStatusProjector

def test_projection_schema_is_central_only_sql_contract():
    sql = RuntimeStatusProjector.CREATE_TABLE_SQL.lower()
    assert "create table if not exists radmon_runtime_status" in sql
    assert "policy_state" in sql
    assert "underlying_dose_status" in sql
    assert "suppression_expires_at" in sql
```

Add a fake MariaDB connection test that calls `project()` twice and asserts one `INSERT ... ON DUPLICATE KEY UPDATE` path rather than source-schema DDL.

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_runtime_status_projection.py tests/test_security.py`
Expected: projection tests fail; permission test fails until role matrix is updated.

- [ ] **Step 3: Implement the projector**

Use exactly this central table contract:

```sql
CREATE TABLE IF NOT EXISTS radmon_runtime_status (
  serid INT PRIMARY KEY,
  policy_state VARCHAR(32) NOT NULL,
  trigger_count INT NOT NULL,
  retrigger_locked TINYINT NOT NULL,
  suppressed TINYINT NOT NULL,
  suppression_expires_at DATETIME NULL,
  suppression_pic VARCHAR(128) NULL,
  suppression_reason VARCHAR(1000) NULL,
  underlying_dose_status VARCHAR(16) NOT NULL,
  updated_at DATETIME NOT NULL
)
```

`project()` uses `INSERT ... ON DUPLICATE KEY UPDATE`. It must never receive a source connection; instantiate it only from central `Settings`.

- [ ] **Step 4: Build all policy services in `build_secure_services()`**

Construct in this order:

```python
policy_store = AlarmPolicyStore(security)
policy_store.ensure_schema()
projector = RuntimeStatusProjector(settings)
policy = AlarmPolicyService(policy_store, audit, projector=projector)
alarm_control = AlarmControlService(..., policy_store=policy_store, policy=policy)
suppression = AlarmSuppressionService(
    security, policy_store, policy, audit,
    alarm_control=alarm_control,
)
```

Add the four objects to `SecureServices`.

Update role permissions so Administrator and Operator include `suppress_alarm`; Viewer does not.

- [ ] **Step 5: Enforce startup ordering in `central_server.py`**

Immediately after `build_secure_services(settings)`, run central projection DDL before starting LAN threads:

```python
services.runtime_status_projector.ensure_schema()
services.alarm_policy.restore_and_reconcile_current_state()
```

`restore_and_reconcile_current_state()` must not notify historical events. Normal notifications are enabled only after `LanRuntime.start()` has completed its first live policy cycle; implement this with a persisted/hydrated flag on the policy service rather than sleeping.

- [ ] **Step 6: Run projection/security/central wiring tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_runtime_status_projection.py tests/test_security.py tests/test_central_archive_wiring.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/runtime_status.py radmon/security.py radmon/secure_services.py central_server.py tests/test_runtime_status_projection.py tests/test_security.py
git commit -m "feat: wire alarm policy services and runtime projection"
```

---

### Task 6: Add authenticated policy and suppression API endpoints

**Files:**
- Modify: `radmon/secure_api.py`
- Modify: `central_server.py`
- Test: `tests/test_alarm_policy_api.py`

**Interfaces:**
- Consumes: `alarm_policy` and `alarm_suppression` services from Task 5.
- Produces endpoints exactly as specified:
  - `GET /api/v1/control/alarm-events`
  - `POST /api/v1/control/alarm-events/{event_id}/response`
  - `GET /api/v1/control/alarm-policy/{serid}`
  - `GET /api/v1/control/suppressions`
  - `POST /api/v1/control/suppressions/{serid}`

- [ ] **Step 1: Write API tests**

```python
from fastapi.testclient import TestClient


def test_viewer_cannot_start_suppression(app_with_users):
    client, login = app_with_users("viewer")
    response = client.post("/api/v1/control/suppressions/5201", json={
        "pin":"9999", "duration_seconds":900, "pic":"Viewer",
        "reason":"Calibration", "auto_resume_on_normal":True,
    })
    assert response.status_code == 403


def test_operator_can_start_and_list_suppression(app_with_users):
    client, login = app_with_users("operator")
    response = client.post("/api/v1/control/suppressions/5201", json={
        "pin":"1357", "duration_seconds":900, "pic":"Budi",
        "reason":"Calibration", "auto_resume_on_normal":True,
    })
    assert response.status_code == 200
    listed = client.get("/api/v1/control/suppressions")
    assert listed.status_code == 200
    assert listed.json()[0]["serid"] == 5201
```

Also test: unauthenticated 401, invalid duration 409/422, missing reason 422, overlap 409, policy GET, policy-event response, and compatibility `/api/v1/control/alarms` still returns a response.

- [ ] **Step 2: Run API tests and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_api.py`
Expected: FAIL/404 before routes exist.

- [ ] **Step 3: Add request models and routes**

Add Pydantic models:

```python
class SuppressionRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    duration_seconds: int = Field(ge=60, le=86400)
    pic: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    auto_resume_on_normal: bool = True

class PolicyResponseRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=8)
    action: str = Field(min_length=1, max_length=128)
    pic: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=1000)
```

Extend `attach_secure_routes(..., alarm_policy=None, alarm_suppression=None)` and map service validation failures to 409, permissions to 403, missing event/detector to 404.

- [ ] **Step 4: Run API tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_api.py tests/test_archive_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/secure_api.py central_server.py tests/test_alarm_policy_api.py
git commit -m "feat: expose alarm policy control api"
```

---

### Task 7: Migrate desktop Alarm/Recent/status strip to policy events and add timed suppression UI

**Files:**
- Create: `radmon/admin/suppression_dialog.py`
- Modify: `radmon/secure_context.py`
- Modify: `radmon/admin/alarm_page.py`
- Modify: `radmon/admin/recent_page.py`
- Modify: `radmon/admin/main_window.py`
- Modify: `main.py`
- Test: `tests/test_alarm_suppression_ui.py`

**Interfaces:**
- `SecurityContext` gains `alarm_policy` and `alarm_suppression`.
- `SuppressionDialog` exposes `duration_seconds()`, `pic`, `reason`, `auto_resume`, `pin` after acceptance.
- `AlarmPage` reads `context.alarm_policy.list_events(...)`, not raw `alarm_mirror.list_alarms(...)` for operator-facing rows.

- [ ] **Step 1: Write Qt UI tests**

```python
# tests/test_alarm_suppression_ui.py
from PySide6.QtWidgets import QApplication
from radmon.admin.suppression_dialog import SuppressionDialog


def app():
    return QApplication.instance() or QApplication([])


def test_suppression_dialog_defaults_auto_resume_checked():
    app()
    dialog = SuppressionDialog(
        serid=5201, station_name="IS-1 Gd.52", dose_rate=170.0,
        underlying_status="ALARM", default_pic="Operator A",
    )
    assert dialog.auto_resume.isChecked() is True
    assert dialog.duration_seconds() == 300
    assert "Measurements" in dialog.notice.text() or "measurement" in dialog.notice.text().lower()


def test_alarm_page_has_suppress_button_and_policy_columns():
    from radmon.admin.alarm_page import AlarmPage
    assert "Policy" in AlarmPage.HEADERS
    assert "Underlying" in AlarmPage.HEADERS
```

Add smoke assertions that Recent and station details display `SUPPRESSED`, PIC/reason/remaining time while still rendering dose rate.

- [ ] **Step 2: Run UI tests and verify failure**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_suppression_ui.py`
Expected: FAIL before dialog/UI migration exists.

- [ ] **Step 3: Implement the suppression dialog**

Dialog controls:

```text
Detector: read-only
Current dose: read-only
Dose status: read-only
Duration preset: 5 / 15 / 30 / 60 / Custom
Custom minutes: 1..1440
PIC: required, prefilled from identity display name
Reason: required multiline text
[x] Aktifkan kembali otomatis saat laju dosis kembali NORMAL
PIN: 4..8 digits
Notice: measurements continue; alarm surfacing/notification is suppressed
```

Keep the auto-resume checkbox checked by default.

- [ ] **Step 4: Render policy state everywhere without hiding dose**

Use effective display strings:

```python
if snapshot["policy_state"] == "SUPPRESSED":
    badge = "SUPPRESSED"
    detail = (
        f"Dose status: {snapshot['underlying_dose_status']} · "
        f"PIC: {snapshot.get('suppression_pic') or '-'} · "
        f"Reason: {snapshot.get('suppression_reason') or '-'}"
    )
```

Alarm page policy rows must store `event_id` in `Qt.UserRole`, and response must call `context.alarm_control.respond_policy_event(...)`. Add `Suppress Alarm...` beside the response button and in the selected-station action area. Disable suppression for Viewer.

The security alarm strip must read active operator-facing policy ALARM events only; SUPPRESSED and RETRIGGER_LOCKED should appear as status rows but must not be formatted as active audible alarms.

- [ ] **Step 5: Populate new services into desktop context**

In `main.py`:

```python
SecurityContext(
    ...,
    alarm_policy=secure.alarm_policy,
    alarm_suppression=secure.alarm_suppression,
)
```

- [ ] **Step 6: Run UI and existing desktop smoke tests**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_suppression_ui.py tests/test_qt_smoke.py tests/test_admin_startup_smoke.py tests/test_production_integration_fix.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add radmon/admin/suppression_dialog.py radmon/secure_context.py radmon/admin/alarm_page.py radmon/admin/recent_page.py radmon/admin/main_window.py main.py tests/test_alarm_suppression_ui.py
git commit -m "feat: add desktop alarm suppression workflow"
```

---

### Task 8: Add Grafana SUPPRESSED projection/status without regressing WIB behavior

**Files:**
- Create: `radmon/grafana_policy_revision.py`
- Modify: `radmon/__init__.py`
- Test: `tests/test_grafana_alarm_policy.py`

**Interfaces:**
- Consumes central `radmon_runtime_status` from Task 5.
- Wraps the already-applied WIB Grafana builders; does not replace time conversion helpers.

- [ ] **Step 1: Write Grafana SQL/payload tests**

```python
# tests/test_grafana_alarm_policy.py
from radmon.grafana_tv import build_dashboard_payloads


def test_operation_status_joins_runtime_policy_and_keeps_underlying_dose():
    operation = build_dashboard_payloads()[2]
    table = next(p for p in operation["panels"] if p.get("description") == "operational-condition")
    sql = table["targets"][0]["rawSql"]
    assert "radmon_runtime_status" in sql
    assert "SUPPRESSED" in sql
    assert "underlying" in sql.lower()
    assert "doserate" in sql.lower()


def test_wib_epoch_conversion_is_still_present():
    dashboards = build_dashboard_payloads()
    payload = str(dashboards)
    assert "CONVERT_TZ" in payload
    assert "+07:00" in payload
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_grafana_alarm_policy.py tests/test_grafana_wib_time.py`
Expected: first policy JOIN test fails; existing WIB tests stay green.

- [ ] **Step 3: Wrap status relation after WIB revision**

Create relation logic equivalent to:

```sql
SELECT
  v.serid, v.name, v.location, v.warnlevel, v.alarmlevel, v.maxidlemin,
  v.dtom, v.doserate,
  COALESCE(r.underlying_dose_status,
    CASE
      WHEN v.doserate >= v.alarmlevel THEN 'ALARM'
      WHEN v.doserate >= v.warnlevel THEN 'ALERT'
      ELSE 'NORMAL'
    END) AS underlying_status,
  CASE
    WHEN v.dtom IS NULL OR TIMESTAMPDIFF(SECOND, v.dtom, CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')) > COALESCE(v.maxidlemin,30)*60 THEN 'OFFLINE'
    WHEN COALESCE(r.suppressed,0) = 1 THEN 'SUPPRESSED'
    WHEN v.doserate >= v.alarmlevel THEN 'ALARM'
    WHEN v.doserate >= v.warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS status,
  r.trigger_count, r.retrigger_locked,
  r.suppression_expires_at, r.suppression_pic, r.suppression_reason
FROM vrecent v
LEFT JOIN radmon_runtime_status r ON r.serid = v.serid
```

Status sort order must be `OFFLINE`, `SUPPRESSED`, `ALARM`, `ALERT`, `NORMAL`. Add mappings for SUPPRESSED and detail columns/tooltips without removing dose.

Apply `grafana_policy_revision` **after** `grafana_wib_revision` in `radmon/__init__.py`.

- [ ] **Step 4: Run Grafana tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_grafana_alarm_policy.py tests/test_grafana_wib_time.py tests/test_grafana_tv.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/grafana_policy_revision.py radmon/__init__.py tests/test_grafana_alarm_policy.py
git commit -m "feat: show suppression state in grafana"
```

---

### Task 9: Switch WhatsApp/notification delivery to persisted operator-facing policy events

**Files:**
- Modify: `radmon/whatsapp.py`
- Modify: `central_server.py`
- Test: `tests/test_alarm_policy_notifications.py`

**Interfaces:**
- `WhatsAppAlarmDispatcher` consumes `AlarmPolicyService`/store event listing instead of raw `RemoteAlarmMirror` rows.
- Only `kind == "ALARM"`, `status == "ACTIVE"`, `notification_sent_at is None` may send.

- [ ] **Step 1: Write notification idempotency tests**

```python
# tests/test_alarm_policy_notifications.py

def test_suppressed_locked_and_historical_events_never_notify(policy_fixture):
    dispatcher, sender, store = policy_fixture
    store.seed_event(kind="SUPPRESSED", status="AUTO_SILENCED", event_key="s1")
    store.seed_event(kind="ALARM", status="RESPONDED", event_key="a1")
    assert dispatcher.run_once() == 0
    assert sender.messages == []


def test_active_alarm_notifies_once_across_dispatcher_restart(policy_fixture):
    dispatcher, sender, store = policy_fixture
    event = store.seed_event(kind="ALARM", status="ACTIVE", event_key="a2")
    assert dispatcher.run_once() == 1
    restarted = type(dispatcher)(dispatcher.policy, sender, now=dispatcher.now)
    assert restarted.run_once() == 0
    assert len(sender.messages) == 1
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_notifications.py`
Expected: FAIL because dispatcher still reads raw mirror rows.

- [ ] **Step 3: Update dispatcher**

Replace raw alarm selection with:

```python
for item in self.policy.list_events(active_only=True, notify_pending_only=True, limit=500):
    if item["kind"] != "ALARM":
        continue
    self.sender.send(self._message(item))
    self.policy.mark_notification_sent(item["event_id"], self.now())
```

Message formatting may keep source/serid/value/threshold, but must use policy event fields and `trigger_index` so #1/#2/#3 are distinguishable.

Wire `WhatsAppAlarmDispatcher(services.alarm_policy, sender)` in `central_server.py`.

- [ ] **Step 4: Run notification and legacy WhatsApp tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_alarm_policy_notifications.py tests/test_whatsapp.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add radmon/whatsapp.py central_server.py tests/test_alarm_policy_notifications.py
git commit -m "feat: notify from policy alarms only"
```

---

### Task 10: Full restart/concurrency/regression verification and operator documentation

**Files:**
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/manual/user-manual.html`
- Modify: `README.md`
- Test: extend `tests/test_alarm_policy.py`, `tests/test_alarm_suppression.py`, `tests/test_alarm_policy_integration.py`

**Interfaces:**
- No new runtime interface; this task closes acceptance criteria and documents exact operator behavior.

- [ ] **Step 1: Add concurrency/restart tests**

Add tests using `threading.Barrier` with two worker threads attempting the first HIGH evaluation simultaneously; assert one ACTIVE ALARM event and `trigger_count == 1`. Add a parallel suppression-start test; assert one succeeds and the other gets conflict. Re-open `SecurityStore`/`AlarmPolicyStore` against the same SQLite file and assert active suppression, trigger count, lock, and `notification_sent_at` survive restart.

- [ ] **Step 2: Add regression tests for historical seed and source recovery**

Feed `_historical_seed=True` raw rows through `process_cycle()` and assert no policy notification candidate is created. Simulate failed source silence followed by success on the next bounded retry; assert only the raw row state changes from FAILED/PENDING to CONFIRMED and no second operator-facing event appears.

- [ ] **Step 3: Run targeted policy suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_alarm_policy_store.py \
  tests/test_alarm_policy.py \
  tests/test_alarm_suppression.py \
  tests/test_alarm_policy_integration.py \
  tests/test_alarm_policy_api.py \
  tests/test_alarm_suppression_ui.py \
  tests/test_runtime_status_projection.py \
  tests/test_grafana_alarm_policy.py \
  tests/test_alarm_policy_notifications.py
```

Expected: PASS.

- [ ] **Step 4: Update user/operator documentation**

Document these exact behaviors:

```text
Alarm burst: maximum 3 surfaced ALARMs within the 5-minute burst rule.
After #3: RETRIGGER LOCKED until dose < LOW/WARN.
Suppression: timed only, 1 minute..24 hours, PIN + PIC + reason required.
Auto resume: optional; when enabled, suppression ends when dose < LOW/WARN.
SUPPRESSED: measurements continue and actual dose/underlying status remain visible.
Anti-spam: at most one SUPPRESSED operator-facing event per suppression session.
```

Also document that source history is preserved and source-side silence failures are visible/audited.

- [ ] **Step 5: Run the full CI-equivalent test suite**

Run: `QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
Expected: all tests PASS.

Run: `python -m compileall -q main.py central_server.py radmon`
Expected: exit code 0.

Run the same Grafana payload validation block from `.github/workflows/ci.yml` and verify all dashboard payloads serialize, every dashboard refresh remains `2s`, and the playlist remains 15 items at `10s`.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/USER-MANUAL.md docs/manual/user-manual.html tests
git commit -m "docs: document alarm suppression policy"
```

- [ ] **Step 7: Verify the final `main` SHA in CI**

Push `main`, wait for GitHub Actions `CI`, confirm pytest, compileall, and Grafana validation are green for the exact final commit SHA. Do not claim production LAN/hardware verification from CI; production validation on PC `.2` is a separate commissioning step.
