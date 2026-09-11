"""Final alarm-policy integration over the production LAN/safety layers.

This patch is deliberately applied after the existing production safety
wrappers.  It keeps source MariaDB schemas untouched: policy metadata and retry
state live only in the central SQLite sidecar, while source silence uses the
existing legacy ``alarm`` UPDATE contract.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any


_SILENCE_DECISIONS = {"SUPPRESSED", "RETRIGGER_LOCKED", "COALESCED_DUPLICATE"}
_BACKOFF_SECONDS = (5, 15, 30, 60)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_retry_column(store) -> None:
    with store.security._connection() as db:
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(remote_alarm_state)")}
        if "source_silence_attempts" not in columns:
            db.execute(
                "ALTER TABLE remote_alarm_state ADD COLUMN source_silence_attempts INTEGER NOT NULL DEFAULT 0"
            )


def _pending_alarm_rows(alarm_mirror, source_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Return mirrored source rows that policy has not classified yet."""
    if alarm_mirror is None:
        return []
    with alarm_mirror.store._connection() as db:
        rows = db.execute(
            """
SELECT serid, remote_serid, event_time, level, measured_value, threshold,
       hit_count, notification_sent_at
FROM remote_alarm_state
WHERE source_id = ? AND policy_decision IS NULL
ORDER BY event_time ASC, serid ASC
LIMIT ?
""",
            (str(source_id), max(1, int(limit))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "serid": int(row[0]),
                "_remote_serid": int(row[1]) if row[1] is not None else int(row[0]),
                "dtoa": datetime.fromisoformat(str(row[2])),
                "lvl": 2 if str(row[3]).upper() == "ALARM" else 1,
                "mvalue": row[4],
                "thvalue": row[5],
                "nhit": row[6],
                # Legacy mirror marks initial/backfilled/already-handled source
                # rows as already-notified. They remain evidence only.
                "_historical_seed": row[7] is not None,
            }
        )
    return result


def _mapped_live_rows(aggregator, source) -> list[dict[str, Any]]:
    remote = aggregator.remote_factory(source)
    mapped: list[dict[str, Any]] = []
    for row in remote.live_rows():
        remote_serid = int(row["serid"])
        central_serid = aggregator.checkpoints.store.resolve_station(source.source_id, remote_serid)
        item = dict(row)
        item["_remote_serid"] = remote_serid
        item["serid"] = central_serid
        mapped.append(item)
    return mapped


def _retry_source_silences(aggregator, source, alarm_policy) -> None:
    """Retry at most 25 source silences using 5/15/30/60-second backoff."""
    store = alarm_policy.store
    _ensure_retry_column(store)
    now = alarm_policy.now() if callable(getattr(alarm_policy, "now", None)) else _utcnow()
    pending = store.pending_source_silences(source.source_id, at=now, limit=25)
    if not pending:
        return
    remote = aggregator.remote_factory(source)
    for item in pending:
        with store.security._connection() as db:
            row = db.execute(
                """SELECT source_silence_attempts FROM remote_alarm_state
                   WHERE source_id=? AND serid=? AND event_time=?""",
                (item["source_id"], int(item["serid"]), item["event_time"].isoformat()),
            ).fetchone()
            attempts = int(row[0] or 0) if row else 0
        try:
            ok = bool(
                remote.respond_alarm(
                    int(item.get("remote_serid") or item["serid"]),
                    item["event_time"],
                    action="Suppressed",
                    pic="RadMon Policy",
                    note="Central policy auto-silence",
                    at=now,
                )
            )
            if not ok:
                raise RuntimeError("source menolak alarm silence")
            store.mark_source_silence_result(
                item["source_id"], item["serid"], item["event_time"], state="CONFIRMED"
            )
            with store.security._connection() as db:
                db.execute(
                    """UPDATE remote_alarm_state SET source_silence_attempts=?
                       WHERE source_id=? AND serid=? AND event_time=?""",
                    (attempts + 1, item["source_id"], int(item["serid"]), item["event_time"].isoformat()),
                )
        except Exception as exc:
            next_attempt = attempts + 1
            delay = _BACKOFF_SECONDS[min(attempts, len(_BACKOFF_SECONDS) - 1)]
            store.mark_source_silence_result(
                item["source_id"], item["serid"], item["event_time"],
                state="FAILED", retry_at=now + timedelta(seconds=delay),
            )
            with store.security._connection() as db:
                db.execute(
                    """UPDATE remote_alarm_state SET source_silence_attempts=?
                       WHERE source_id=? AND serid=? AND event_time=?""",
                    (next_attempt, item["source_id"], int(item["serid"]), item["event_time"].isoformat()),
                )
            audit = getattr(alarm_policy, "audit", None)
            if audit is not None:
                audit.record(
                    "SUPPRESSION_SOURCE_SILENCE_FAILED", None, "alarm",
                    f"{item['source_id']}:{item['serid']}:{item['event_time'].isoformat()}",
                    success=False, reason=str(exc), source=item["source_id"],
                )


def apply() -> None:
    from .alarm_policy_store import AlarmPolicyStore
    from . import alarm_policy as policy_module
    from . import lan as lan_module
    from . import lan_runtime as runtime_module
    from . import remote_alarm as alarm_module

    # ----- raw mirror policy metadata helpers -----
    def policy_store_for_mirror(self):
        store = getattr(self, "policy_store", None)
        if store is None:
            store = AlarmPolicyStore(self.store)
            self.policy_store = store
        return store

    def annotate_policy(self, source_id, serid, event_time, **kwargs):
        return policy_store_for_mirror(self).annotate_raw_alarm(
            source_id, serid, event_time, **kwargs
        )

    def pending_source_silences(self, source_id=None, *, at=None, limit=25):
        return policy_store_for_mirror(self).pending_source_silences(
            source_id, at=at, limit=limit
        )

    def mark_source_silence_result(self, source_id, serid, event_time, *, state, retry_at=None):
        return policy_store_for_mirror(self).mark_source_silence_result(
            source_id, serid, event_time, state=state, retry_at=retry_at
        )

    alarm_module.RemoteAlarmMirror.annotate_policy = annotate_policy
    alarm_module.RemoteAlarmMirror.pending_source_silences = pending_source_silences
    alarm_module.RemoteAlarmMirror.mark_source_silence_result = mark_source_silence_result

    # ----- source write-through for operator responses -----
    def policy_store_for_control(self):
        store = getattr(self, "policy_store", None)
        if store is None:
            store = AlarmPolicyStore(self.security)
            self.policy_store = store
        return store

    def silence_source_row(
        self, source_id: str, serid: int, event_time: datetime, *, action: str, pic: str, reason: str
    ) -> bool:
        remote = self.remote_factory(str(source_id))
        responder = getattr(remote, "respond_alarm", None)
        if not callable(responder):
            raise RuntimeError("source tidak mendukung alarm response")
        at = self.now()
        return bool(
            responder(
                int(serid), event_time, action=action, pic=pic, note=reason, at=at
            )
        )

    def respond_policy_event(self, identity, pin: str, event_id: str, *, action: str, pic: str, reason: str):
        self.security.require_sensitive(identity, "ack_alarm", pin)
        action_text = str(action or "").strip()
        pic_text = str(pic or "").strip()
        reason_text = str(reason or "").strip()
        if not action_text or not pic_text:
            raise ValueError("Action dan PIC wajib diisi")
        store = policy_store_for_control(self)
        event = store.get_event(str(event_id))
        if event is None:
            raise RuntimeError("policy event tidak ditemukan")
        if event.status != "ACTIVE":
            raise RuntimeError("policy event sudah ditangani")
        at = self.now()
        with self.security._connection() as db:
            rows = db.execute(
                """SELECT source_id, serid, remote_serid, event_time
                   FROM remote_alarm_state
                   WHERE policy_event_id=? ORDER BY event_time""",
                (str(event_id),),
            ).fetchall()
        for row in rows:
            source_id = str(row[0])
            central_serid = int(row[1])
            remote_serid = int(row[2]) if row[2] is not None else central_serid
            event_time = datetime.fromisoformat(str(row[3]))
            try:
                if not silence_source_row(
                    self, source_id, remote_serid, event_time,
                    action=action_text, pic=pic_text, reason=reason_text,
                ):
                    raise RuntimeError("source menolak alarm response")
                store.mark_source_silence_result(
                    source_id, central_serid, event_time, state="CONFIRMED"
                )
            except Exception as exc:
                store.mark_source_silence_result(
                    source_id, central_serid, event_time, state="FAILED",
                    retry_at=at + timedelta(seconds=5),
                )
                self.audit.record(
                    "ALARM_POLICY_SOURCE_RESPONSE", identity, "alarm", str(event_id),
                    success=False, reason=str(exc), source=source_id,
                )
        policy = getattr(self, "policy", None)
        if policy is not None:
            responded = policy.mark_event_responded(
                str(event_id), at, pic_text, action_text, reason_text
            )
        else:
            responded = store.respond_event(
                str(event_id), at, pic_text, action_text, reason_text
            )
        self.audit.record(
            "ALARM_POLICY_RESPONSE", identity, "alarm", str(event_id),
            before=asdict(event), after=asdict(responded), source=event.source_id,
        )
        return asdict(responded)

    alarm_module.AlarmControlService.silence_source_row = silence_source_row
    alarm_module.AlarmControlService.respond_policy_event = respond_policy_event

    # Mark non-visible source alarm rows for bounded source-silence retry.
    previous_observe = policy_module.AlarmPolicyService.observe_source_alarm

    def observe_source_alarm(self, source_id: str, row: dict[str, Any]):
        result = previous_observe(self, source_id, row)
        if bool(row.get("_historical_seed")):
            return result
        decision = str(result.get("decision") or "")
        if decision not in _SILENCE_DECISIONS:
            return result
        event_time = self._measurement_time(row)
        suppression = self.store.active_suppression(int(row["serid"]))
        policy_event_id = result.get("policy_event_id")
        if policy_event_id is None and suppression is not None:
            for item in self.store.list_policy_events(serid=int(row["serid"]), limit=50):
                if item.kind == "SUPPRESSED" and item.suppression_id == suppression.suppression_id:
                    policy_event_id = item.event_id
                    break
        self.store.annotate_raw_alarm(
            source_id,
            int(row["serid"]),
            event_time,
            policy_decision=decision,
            suppression_id=suppression.suppression_id if suppression else None,
            operator_visible=False,
            policy_event_id=policy_event_id,
            source_silence_state="PENDING",
            source_silence_retry_at=self.now(),
        )
        result["policy_event_id"] = policy_event_id
        return result

    policy_module.AlarmPolicyService.observe_source_alarm = observe_source_alarm

    # Attach policy to runtime aggregators without changing source ownership.
    previous_aggregator = runtime_module.LanRuntime._aggregator

    def _aggregator(self, batch_size=None):
        aggregator = previous_aggregator(self, batch_size)
        aggregator.alarm_policy = getattr(self.services, "alarm_policy", None)
        return aggregator

    runtime_module.LanRuntime._aggregator = _aggregator

    # Wrap the already-final safety live cycle. Raw alarms were mirrored by the
    # inner cycle; we classify only sidecar rows whose policy_decision is NULL.
    previous_run_live = lan_module.LanAggregator.run_live_once

    def run_live_once(self, source):
        result = previous_run_live(self, source)
        alarm_policy = getattr(self, "alarm_policy", None)
        if result.error or alarm_policy is None:
            return result
        try:
            mapped_live = _mapped_live_rows(self, source)
            mapped_alarms = _pending_alarm_rows(
                getattr(self, "alarm_mirror", None), source.source_id, limit=500
            )
            alarm_policy.process_cycle(source.source_id, mapped_live, mapped_alarms)
            _retry_source_silences(self, source, alarm_policy)
        except Exception as exc:
            result.error = str(exc)
        return result

    lan_module.LanAggregator.run_live_once = run_live_once
