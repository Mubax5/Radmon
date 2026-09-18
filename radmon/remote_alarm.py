from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .audit import AuditTrail
from .security import SecurityStore, UserIdentity


class RemoteAlarmMirror:
    def __init__(self, store: SecurityStore) -> None:
        self.store = store

    @staticmethod
    def _event_time(row: dict[str, Any]) -> datetime:
        value = row.get("dtoa", row.get("dtom"))
        if not isinstance(value, datetime):
            raise ValueError("alarm event time tidak valid")
        return value

    @staticmethod
    def _level(row: dict[str, Any]) -> str:
        if "lvl" in row:
            return "ALARM" if int(row.get("lvl") or 0) >= 2 else "ALERT"
        value = str(row.get("type") or "ALERT").upper()
        return value if value in {"ALERT", "ALARM"} else "ALERT"

    def mirror(self, source_id: str, rows: list[dict[str, Any]]) -> int:
        self._ensure_active_schema()
        changed = 0
        observed_at = datetime.now(timezone.utc).isoformat()
        with self.store._connection() as connection:
            for row in rows:
                event_time = self._event_time(row)
                event_iso = event_time.isoformat()
                serid = int(row['serid'])
                remote_serid = int(row.get('_remote_serid', serid))
                acknowledged_at = row.get('i_op')
                ack_iso = acknowledged_at.isoformat() if isinstance(acknowledged_at, datetime) else None
                if 'i_flag' in row:
                    is_active = 0 if int(row.get('i_flag') or 0) else 1
                else:
                    is_active = 0 if ack_iso or bool(row.get('ack')) else 1
                source_i_flag = 1 if 'i_flag' in row and int(row.get('i_flag') or 0) else 0
                historical = bool(row.get('_historical_seed'))
                already_notified = historical or not bool(is_active) or bool(row.get('ack')) or (ack_iso is not None)
                notification_sent_at = ack_iso or (event_iso if already_notified else None)
                before_changes = connection.total_changes
                connection.execute('\nINSERT INTO remote_alarm_state\n  (source_id, serid, remote_serid, event_time, level, measured_value,\n   threshold, hit_count, acknowledged_at, pic, action, note,\n   notification_sent_at, is_active, source_i_flag, source_observed_at, source_observation_version)\nVALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)\nON CONFLICT(source_id, serid, event_time) DO UPDATE SET\n  remote_serid = excluded.remote_serid,\n  level = excluded.level,\n  measured_value = COALESCE(excluded.measured_value, measured_value),\n  threshold = COALESCE(excluded.threshold, threshold),\n  hit_count = COALESCE(excluded.hit_count, hit_count),\n  is_active = excluded.is_active,\n  source_i_flag = excluded.source_i_flag,\n  source_observed_at = excluded.source_observed_at,\n  acknowledged_at = CASE\n    WHEN excluded.is_active = 1 THEN NULL\n    ELSE COALESCE(excluded.acknowledged_at, acknowledged_at)\n  END,\n  pic = COALESCE(excluded.pic, pic),\n  note = COALESCE(excluded.note, note),\n  notification_sent_at = COALESCE(notification_sent_at, excluded.notification_sent_at),\n  source_observation_version = COALESCE(source_observation_version, 0) + 1\n', (source_id, serid, remote_serid, event_iso, self._level(row), row.get('mvalue'), row.get('thvalue'), row.get('nhit'), ack_iso, row.get('pic'), None, row.get('note'), notification_sent_at, is_active, source_i_flag, observed_at))
                if connection.total_changes > before_changes:
                    changed += 1
        return changed

    @staticmethod
    def _row(row):
        keys = ('source_id', 'serid', 'remote_serid', 'event_time', 'level', 'measured_value', 'threshold', 'hit_count', 'acknowledged_at', 'pic', 'action', 'note', 'notification_sent_at', 'is_active')
        item = dict(zip(keys, row))
        for key in ('event_time', 'acknowledged_at', 'notification_sent_at'):
            if item[key]:
                item[key] = datetime.fromisoformat(str(item[key]))
        item['is_active'] = bool(item.get('is_active'))
        return item

    def list_alarms(self, *, active_only: bool=False, limit: int=500):
        self._ensure_active_schema()
        clause = 'WHERE is_active = 1' if active_only else ''
        with self.store._connection() as connection:
            rows = connection.execute(f'\nSELECT source_id, serid, remote_serid, event_time, level, measured_value,\n       threshold, hit_count, acknowledged_at, pic, action, note,\n       notification_sent_at, is_active\nFROM remote_alarm_state {clause}\nORDER BY event_time DESC LIMIT ?\n', (max(1, int(limit)),)).fetchall()
        return [self._row(row) for row in rows]

    def get(self, source_id: str, serid: int, event_time: datetime):
        self._ensure_active_schema()
        with self.store._connection() as connection:
            row = connection.execute('\nSELECT source_id, serid, remote_serid, event_time, level, measured_value,\n       threshold, hit_count, acknowledged_at, pic, action, note,\n       notification_sent_at, is_active\nFROM remote_alarm_state\nWHERE source_id = ? AND serid = ? AND event_time = ?\n', (source_id, int(serid), event_time.isoformat())).fetchone()
        return self._row(row) if row else None

    def mark_acknowledged(self, source_id: str, serid: int, event_time: datetime, *, acknowledged_at: datetime, pic: str, action: str, note: str):
        self._ensure_active_schema()
        with self.store._connection() as connection:
            cursor = connection.execute('\nUPDATE remote_alarm_state\nSET acknowledged_at = ?, pic = ?, action = ?, note = ?, is_active = 0\nWHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1\n', (acknowledged_at.isoformat(), pic, action, note, source_id, int(serid), event_time.isoformat()))
            if cursor.rowcount != 1:
                raise RuntimeError('alarm sudah ditangani atau tidak ditemukan')
        item = self.get( source_id, serid, event_time)
        if item is None:
            raise RuntimeError('alarm tidak ditemukan setelah response')
        return item

    def mark_notification_sent(self, source_id: str, serid: int, event_time: datetime, at: datetime) -> None:
        with self.store._connection() as connection:
            connection.execute(
                """
UPDATE remote_alarm_state SET notification_sent_at = ?
WHERE source_id = ? AND serid = ? AND event_time = ?
""",
                (at.isoformat(), source_id, int(serid), event_time.isoformat()),
            )

    def _ensure_active_schema(self) -> None:
        # SecurityStore applies this additive schema during startup.
        return

    def reconcile_source_active_keys(self, source_id: str, active_keys: set[tuple[int, datetime]]) -> list[tuple[int, datetime]]:
        self._ensure_active_schema()
        normalized = {(int(serid), when.isoformat()) for serid, when in active_keys if isinstance(when, datetime)}
        handled: list[tuple[int, datetime]] = []
        with self.store._connection() as connection:
            rows = connection.execute('\nSELECT serid, event_time\nFROM remote_alarm_state\nWHERE source_id = ? AND is_active = 1\n', (str(source_id),)).fetchall()
            for serid, event_text in rows:
                key = (int(serid), str(event_text))
                if key in normalized:
                    continue
                cursor = connection.execute('\nUPDATE remote_alarm_state\nSET is_active = 0, source_observation_version = COALESCE(source_observation_version, 0) + 1\nWHERE source_id = ? AND serid = ? AND event_time = ? AND is_active = 1\n', (str(source_id), int(serid), str(event_text)))
                if cursor.rowcount == 1:
                    handled.append((int(serid), datetime.fromisoformat(str(event_text))))
        return handled

    def _policy_store(self):
        from .alarm_policy_store import AlarmPolicyStore
        store = getattr(self, "policy_store", None)
        if store is None:
            store = AlarmPolicyStore(self.store)
            self.policy_store = store
        return store

    def annotate_policy(self, source_id, serid, event_time, **kwargs):
        return self._policy_store().annotate_raw_alarm(source_id, serid, event_time, **kwargs)

    def pending_source_silences(self, source_id=None, *, at=None, limit=25):
        return self._policy_store().pending_source_silences(source_id, at=at, limit=limit)

    def mark_source_silence_result(self, source_id, serid, event_time, *, state, retry_at=None):
        return self._policy_store().mark_source_silence_result(
            source_id, serid, event_time, state=state, retry_at=retry_at
        )


class AlarmControlService:
    def __init__(
        self,
        security: SecurityStore,
        mirror: RemoteAlarmMirror,
        audit: AuditTrail,
        *,
        remote_factory: Callable[[str], Any],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.security = security
        self.mirror = mirror
        self.audit = audit
        self.remote_factory = remote_factory
        self.now = now or datetime.now

    def ack(self, identity, pin: str, source_id: str, serid: int, event_time, *, action: str, pic: str, note: str):
        from .lan import RemoteMariaDBSource
        self.security.require_sensitive(identity, 'ack_alarm', pin)
        if not action.strip() or not pic.strip():
            raise ValueError('Action dan PIC wajib diisi')
        before = self.mirror.get(source_id, serid, event_time)
        if before is None:
            raise RuntimeError('alarm tidak ditemukan')
        if before.get('is_active') is False:
            raise RuntimeError('alarm sudah ditangani')
        remote_serid = int(before.get('remote_serid') or serid)
        at = self.now()
        target_id = f'{source_id}:{serid}:{event_time.isoformat()}'
        try:
            remote = self.remote_factory(source_id)
            responder = getattr(remote, 'respond_alarm', None)
            if callable(responder):
                ok = bool(responder(remote_serid, event_time, action=action.strip(), pic=pic.strip(), note=note.strip(), at=at))
            elif not isinstance(remote, RemoteMariaDBSource) and callable(getattr(remote, 'ack_legacy', None)):
                ok = bool(remote.ack_legacy(remote_serid, event_time, action=action.strip(), pic=pic.strip(), note=note.strip(), at=at))
            else:
                raise RuntimeError('source tidak mendukung response i_flag')
            if not ok:
                raise RuntimeError('source menolak response; alarm mungkin sudah ditangani')
            after = self.mirror.mark_acknowledged(source_id, serid, event_time, acknowledged_at=at, pic=pic.strip(), action=action.strip(), note=note.strip())
        except Exception as exc:
            self.audit.record('ALARM_ACK', identity, 'alarm', target_id, before=before, success=False, reason=str(exc), source=source_id)
            raise
        self.audit.record('ALARM_ACK', identity, 'alarm', target_id, before=before, after=after, source=source_id)
        return after

    def _policy_store(self):
        from .alarm_policy_store import AlarmPolicyStore
        store = getattr(self, "policy_store", None)
        if store is None:
            store = AlarmPolicyStore(self.security)
            self.policy_store = store
        return store

    def silence_source_row(self, source_id: str, serid: int, event_time: datetime, *, action: str, pic: str, reason: str) -> bool:
        remote = self.remote_factory(str(source_id))
        responder = getattr(remote, "respond_alarm", None)
        if not callable(responder):
            raise RuntimeError("source tidak mendukung alarm response")
        at = self.now()
        return bool(responder(int(serid), event_time, action=action, pic=pic, note=reason, at=at))

    def respond_policy_event(self, identity, pin: str, event_id: str, *, action: str, pic: str, reason: str):
        self.security.require_sensitive(identity, "ack_alarm", pin)
        action_text = str(action or "").strip()
        pic_text = str(pic or "").strip()
        reason_text = str(reason or "").strip()
        if not action_text or not pic_text:
            raise ValueError("Action dan PIC wajib diisi")
        store = self._policy_store()
        event = store.get_event(str(event_id))
        if event is None:
            raise RuntimeError("policy event tidak ditemukan")
        if event.status != "ACTIVE":
            raise RuntimeError("policy event sudah ditangani")
        at = self.now()
        with self.security._connection() as db:
            rows = db.execute(
                """SELECT source_id, serid, remote_serid, event_time, suppression_id
                   FROM remote_alarm_state
                   WHERE policy_event_id=? ORDER BY event_time""",
                (str(event_id),),
            ).fetchall()
        if event.source_id and not rows:
            reason_text = "tidak ada baris sumber yang cocok untuk event policy"
            self.audit.record(
                "ALARM_POLICY_SOURCE_RESPONSE", identity, "alarm", str(event_id),
                success=False, reason=reason_text, source=event.source_id,
            )
            raise RuntimeError(reason_text)
        failures = []
        skipped = False
        for row in rows:
            source_id = str(row[0])
            central_serid = int(row[1])
            remote_serid = int(row[2]) if row[2] is not None else central_serid
            event_time = datetime.fromisoformat(str(row[3]))
            suppression_id = row[4]
            responder = lambda: self.silence_source_row(
                        source_id, remote_serid, event_time,
                        action=action_text, pic=pic_text, reason=reason_text,
            )
            active_suppression = store.active_suppression(central_serid)
            if (
                suppression_id
                and active_suppression is not None
                and active_suppression.suppression_id == suppression_id
                and at < active_suppression.expires_at
            ):
                hook = getattr(self, "before_source_silence_claim", None)
                if callable(hook):
                    hook(str(suppression_id))
                state, error = store.dispatch_source_silence(
                    source_id, central_serid, event_time, at=at, responder=responder,
                    backoff_seconds=(5, 15, 30, 60),
                )
            else:
                state, error = store.dispatch_source_response(
                    source_id, central_serid, event_time, at=at, responder=responder,
                )
            if state in {"FAILED", "UNCERTAIN"}:
                self.audit.record(
                    "ALARM_POLICY_SOURCE_RESPONSE", identity, "alarm", str(event_id),
                    success=False,
                    reason=("hasil silence sumber tidak pasti setelah suppression berakhir" if state == "UNCERTAIN" else str(error)),
                    source=source_id,
                )
                failures.append(f"{source_id}: {'hasil tidak pasti' if state == 'UNCERTAIN' else error}")
            elif state in {"SKIPPED", "CANCELLED"}:
                skipped = True
        if failures:
            # A remote i_flag write has not been confirmed for every linked row.
            # Keep the central event active instead of falsely claiming response.
            raise RuntimeError("respons sumber gagal; alarm tetap aktif: " + "; ".join(failures))
        if skipped:
            raise RuntimeError("respons sumber dibatalkan; alarm tetap aktif")
        policy = getattr(self, "policy", None)
        if policy is not None:
            responded = policy.mark_event_responded(str(event_id), at, pic_text, action_text, reason_text)
        else:
            responded = store.respond_event(str(event_id), at, pic_text, action_text, reason_text)
        self.audit.record(
            "ALARM_POLICY_RESPONSE", identity, "alarm", str(event_id),
            before=asdict(event), after=asdict(responded), source=event.source_id,
        )
        return asdict(responded)
