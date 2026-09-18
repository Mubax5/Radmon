from datetime import datetime, timedelta, timezone
import sqlite3

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.security import SecurityStore


def live(at, dose, *, observed=None):
    row = {
        "serid": 5702, "dtom": at, "doserate": dose,
        "warnlevel": 23.0, "alarmlevel": 25.0, "maxidlemin": 5,
    }
    if observed is not None:
        row["_source_observed_at"] = observed
    return row


def test_fresh_warning_and_normal_close_original_alarm_but_only_normal_resets(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    at = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)

    first = policy.evaluate_live(live(at, 25.1), source_id="gd52")
    warning = policy.evaluate_live(live(at + timedelta(seconds=10), 24.0), source_id="gd52")
    closed = store.get_event(first["active_event_id"])

    assert warning["active_event_id"] is None
    assert warning["trigger_count"] == 1
    assert closed.status == "AUTO_RESOLVED_WARNING"
    assert closed.responded_at is None and closed.pic is None
    assert closed.resolution_code == "AUTO_RESOLVED_WARNING"

    normal = policy.evaluate_live(live(at + timedelta(seconds=20), 0.2), source_id="gd52")
    assert normal["trigger_count"] == 0
    assert normal["retrigger_locked"] is False
    assert any(item["action"] == "ALARM_POLICY_AUTO_RESOLVED" for item in audit.list_events())


def test_stale_or_out_of_order_normal_never_closes_active_alarm(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, AuditTrail(security))
    at = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    first = policy.evaluate_live(live(at, 30.0, observed=at), source_id="gd52")

    stale = policy.evaluate_live(
        live(at + timedelta(seconds=1), 0.2, observed=at + timedelta(minutes=10)), source_id="gd52",
    )
    out_of_order = policy.evaluate_live(live(at - timedelta(seconds=1), 0.2, observed=at), source_id="gd52")

    assert stale["underlying_dose_status"] == "UNKNOWN"
    assert out_of_order["active_event_id"] == first["active_event_id"]
    assert store.get_event(first["active_event_id"]).status == "ACTIVE"


def test_source_i_flag_closes_linked_event_without_fabricating_operator_response(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    mirror = RemoteAlarmMirror(security)
    at = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    first = policy.evaluate_live(live(at, 30.0), source_id="gd52")
    raw = {"serid": 5702, "_remote_serid": 2, "dtoa": at, "lvl": 2, "i_flag": 0}
    mirror.mirror("gd52", [raw])
    policy.observe_source_alarm("gd52", raw)
    mirror.mirror("gd52", [dict(raw, i_flag=1)])

    assert policy.reconcile_source_handled("gd52") == 1
    event = store.get_event(first["active_event_id"])
    assert event.status == "SOURCE_HANDLED"
    assert event.responded_at is None and event.pic is None and event.action is None
    assert event.resolution_code == "SOURCE_HANDLED"
    assert any(item["action"] == "ALARM_POLICY_SOURCE_HANDLED" for item in audit.list_events())


def test_legacy_exact_source_row_closes_once_and_preserves_timestamped_evidence(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    mirror = RemoteAlarmMirror(security)
    at = datetime(2026, 9, 16, 9, 47, 51, tzinfo=timezone.utc)
    event_id = policy.evaluate_live(live(at, 57.51), source_id="gd52")["active_event_id"]

    # This models a pre-link migration: policy_event_id is deliberately absent.
    mirror.mirror("gd52", [{
        "serid": 5702, "_remote_serid": 5702, "dtoa": at, "lvl": 2,
        "mvalue": 57.51, "thvalue": 25.0, "i_flag": 1,
        "i_op": at + timedelta(minutes=2),
    }])

    assert policy.reconcile_source_handled("gd52") == 1
    assert policy.reconcile_source_handled("gd52") == 0
    event = store.get_event(event_id)
    assert event.status == "SOURCE_HANDLED"
    assert event.responded_at is None and event.pic is None and event.action is None
    with security._connection() as db:
        lifecycle = db.execute(
            """SELECT source_id, serid, event_occurrence_at, source_event_time, source_i_flag,
                      source_i_op, status, reason
               FROM alarm_policy_source_reconciliation WHERE event_id=?""",
            (event_id,),
        ).fetchone()
    assert lifecycle == (
        "gd52", 5702, at.isoformat(), at.isoformat(), 1,
        (at + timedelta(minutes=2)).isoformat(), "SOURCE_HANDLED", "EXACT_SOURCE_I_FLAG_CONFIRMED",
    )
    assert [item["action"] for item in audit.list_events()].count("ALARM_POLICY_SOURCE_HANDLED") == 1


def test_ambiguous_later_source_rows_remain_active_with_visible_reason(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    mirror = RemoteAlarmMirror(security)
    at = datetime(2026, 9, 16, 9, 47, 51, tzinfo=timezone.utc)
    event_id = policy.evaluate_live(live(at, 57.51), source_id="gd52")["active_event_id"]

    for offset in (1, 2):
        source_at = at + timedelta(seconds=offset)
        mirror.mirror("gd52", [{
            "serid": 5702, "_remote_serid": 5702, "dtoa": source_at, "lvl": 2,
            "i_flag": 1, "i_op": source_at + timedelta(minutes=2),
        }])

    assert policy.reconcile_source_handled("gd52") == 0
    assert store.get_event(event_id).status == "ACTIVE"
    listed = next(item for item in policy.list_events(serid=5702) if item["event_id"] == event_id)
    assert listed["source_reconciliation"]["status"] == "AMBIGUOUS"
    assert listed["source_reconciliation"]["reason"] == "AMBIGUOUS_SOURCE_CORRELATION"
    assert any(item["action"] == "ALARM_POLICY_SOURCE_RECONCILIATION_AMBIGUOUS" for item in audit.list_events())


def test_stale_or_offline_data_never_substitutes_for_exact_source_evidence(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(security)
    store = AlarmPolicyStore(security)
    policy = AlarmPolicyService(store, audit)
    at = datetime(2026, 9, 16, 9, 47, 51, tzinfo=timezone.utc)
    event_id = policy.evaluate_live(live(at, 57.51, observed=at), source_id="gd52")["active_event_id"]

    stale = policy.evaluate_live(
        live(at + timedelta(seconds=1), 0.2, observed=at + timedelta(minutes=10)), source_id="gd52",
    )
    assert stale["underlying_dose_status"] == "UNKNOWN"
    assert policy.reconcile_source_handled("gd52") == 0
    assert store.get_event(event_id).status == "ACTIVE"
    listed = next(item for item in policy.list_events(serid=5702) if item["event_id"] == event_id)
    assert listed["source_reconciliation"]["reason"] == "EXACT_SOURCE_ALARM_NOT_OBSERVED"


def test_policy_schema_migrates_old_runtime_database_without_losing_event_history(tmp_path):
    path = tmp_path / "runtime-security.db"
    security = SecurityStore(path)
    event_id = "old-event"
    with security._connection() as db:
        db.execute(
            """CREATE TABLE alarm_policy_state (
                serid INTEGER PRIMARY KEY, window_started_at TEXT, trigger_count INTEGER NOT NULL,
                retrigger_locked INTEGER NOT NULL, active_event_id TEXT, last_trigger_at TEXT,
                last_normal_at TEXT, updated_at TEXT NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE alarm_policy_event (
                event_id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, serid INTEGER NOT NULL,
                source_id TEXT, remote_serid INTEGER, remote_event_time TEXT, origin TEXT NOT NULL,
                kind TEXT NOT NULL, trigger_index INTEGER, surfaced_at TEXT NOT NULL,
                measured_value REAL, threshold REAL, status TEXT NOT NULL, suppression_id TEXT,
                responded_at TEXT, pic TEXT, action TEXT, reason TEXT, notification_sent_at TEXT
            )"""
        )
        db.execute(
            "INSERT INTO alarm_policy_event VALUES (?, ?, 5702, 'gd52', NULL, NULL, 'central_policy', 'ALARM', 1, ?, 30, 25, 'ACTIVE', NULL, NULL, NULL, NULL, NULL, NULL)",
            (event_id, "old-key", datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc).isoformat()),
        )

    store = AlarmPolicyStore(SecurityStore(path))
    event = store.get_event(event_id)
    with sqlite3.connect(path) as db:
        state_columns = {row[1] for row in db.execute("PRAGMA table_info(alarm_policy_state)")}
        event_columns = {row[1] for row in db.execute("PRAGMA table_info(alarm_policy_event)")}
        versions = [row[0] for row in db.execute("SELECT version FROM alarm_policy_schema_migration")]

    assert event is not None and event.status == "ACTIVE"
    assert {"last_measurement_at"} <= state_columns
    assert {"resolved_at", "resolution_code", "resolution_reason"} <= event_columns
    assert versions == [4]
