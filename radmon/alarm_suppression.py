from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Callable
import uuid

from .alarm_policy_store import SuppressionRecord
from .security import Role, SecurityError


class AlarmSuppressionService:
    """Own the authenticated, timed suppression lifecycle for one detector.

    Suppression affects operator-facing alarm surfacing only. Measurements keep
    flowing and the policy service continues to expose the underlying dose
    condition on every live evaluation.
    """

    MIN_DURATION_SECONDS = 60
    MAX_DURATION_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        security,
        store,
        policy,
        audit,
        *,
        alarm_control=None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.security = security
        self.store = store
        self.policy = policy
        self.audit = audit
        self.alarm_control = alarm_control
        self.now = now or datetime.now

    def _authorize(self, identity, pin: str) -> None:
        # ``suppress_alarm`` is installed by the alarm-policy compatibility
        # revision. Fall back to the existing operator alarm permission while
        # loading older stores so an additive upgrade can bootstrap cleanly.
        permission = "suppress_alarm"
        if identity is None:
            raise SecurityError("aksi tidak diizinkan")
        try:
            allowed = bool(self.security.role_allows(identity.role, permission))
        except Exception:
            allowed = False
        if not allowed:
            if identity.role not in {Role.ADMINISTRATOR, Role.OPERATOR}:
                raise SecurityError("aksi tidak diizinkan")
            permission = "ack_alarm"
        self.security.require_sensitive(identity, permission, pin)

    @staticmethod
    def _create_in_transaction(
        tx,
        *,
        serid: int,
        started_at: datetime,
        expires_at: datetime,
        auto_resume_on_normal: bool,
        pic: str,
        reason: str,
        started_by: str,
    ) -> SuppressionRecord:
        """Insert and read a suppression on the same SQLite transaction.

        Reading through a second SQLite connection before the detector
        transaction commits cannot see the newly inserted row. Keep the write
        and returned record on the owning transaction so creation is atomic.
        """
        suppression_id = str(uuid.uuid4())
        tx.connection.execute(
            """
INSERT INTO alarm_suppression
  (suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
   started_by, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
            (
                suppression_id,
                int(serid),
                started_at.isoformat(),
                expires_at.isoformat(),
                1 if auto_resume_on_normal else 0,
                pic,
                reason,
                started_by,
                started_at.isoformat(),
                started_at.isoformat(),
            ),
        )
        return SuppressionRecord(
            suppression_id=suppression_id,
            serid=int(serid),
            started_at=started_at,
            expires_at=expires_at,
            auto_resume_on_normal=bool(auto_resume_on_normal),
            pic=pic,
            reason=reason,
            started_by=started_by,
            created_at=started_at,
            updated_at=started_at,
        )

    def start(
        self,
        identity,
        pin: str,
        serid: int,
        duration_seconds: int,
        pic: str,
        reason: str,
        auto_resume_on_normal: bool,
    ) -> dict:
        self._authorize(identity, pin)
        duration = int(duration_seconds)
        if not self.MIN_DURATION_SECONDS <= duration <= self.MAX_DURATION_SECONDS:
            raise ValueError("Durasi suppression harus 1 menit sampai 24 jam")
        pic_text = str(pic or "").strip()
        reason_text = str(reason or "").strip()
        if not pic_text:
            raise ValueError("PIC wajib diisi")
        if not reason_text:
            raise ValueError("Alasan suppression wajib diisi")

        started_at = self.now()
        expires_at = started_at + timedelta(seconds=duration)
        event_to_silence: str | None = None

        with self.store.detector_transaction(int(serid)) as tx:
            active = tx.active_suppression
            if active is not None:
                if started_at < active.expires_at:
                    raise RuntimeError("suppression detector masih aktif")
                tx.end_suppression(active.suppression_id, started_at, "EXPIRED")

            state = tx.state
            event_to_silence = state.active_event_id
            if not state.retrigger_locked:
                state.window_started_at = None
                state.trigger_count = 0
                state.active_event_id = None
                state.last_trigger_at = None
                tx.save_state(state, at=started_at)

            suppression = self._create_in_transaction(
                tx,
                serid=int(serid),
                started_at=started_at,
                expires_at=expires_at,
                auto_resume_on_normal=bool(auto_resume_on_normal),
                pic=pic_text,
                reason=reason_text,
                started_by=identity.username,
            )
            tx.active_suppression = suppression
            if event_to_silence:
                self.store.bind_policy_event_to_suppression(
                    event_to_silence, suppression.suppression_id, connection=tx.connection,
                )
                self.store.bind_source_silences_to_suppression(
                    event_to_silence, suppression.suppression_id, connection=tx.connection,
                )

        # Source write-through is best-effort here. The central suppression is
        # canonical and must remain active even when a source host is down.
        if event_to_silence and self.alarm_control is not None:
            responder = getattr(self.alarm_control, "respond_policy_event", None)
            if callable(responder):
                try:
                    responder(
                        identity,
                        pin,
                        event_to_silence,
                        action="Suppressed",
                        pic=pic_text,
                        reason=reason_text,
                    )
                except Exception as exc:
                    self.audit.record(
                        "SUPPRESSION_SOURCE_SILENCE_FAILED",
                        identity,
                        "station",
                        str(int(serid)),
                        success=False,
                        reason=str(exc),
                        source="central",
                    )

        result = asdict(suppression)
        self.audit.record(
            "ALARM_SUPPRESSION_START",
            identity,
            "station",
            str(int(serid)),
            after=result,
            source="central",
        )
        return result

    def list(self, active_only: bool = False, limit: int = 500) -> list[dict]:
        result = []
        for item in self.store.list_suppressions(active_only=bool(active_only), limit=max(1, int(limit))):
            row = asdict(item)
            row["source_silence_state"] = self.store.suppression_source_silence_state(item.suppression_id)
            result.append(row)
        return result

    def end(self, identity, pin: str, serid: int, *, reason: str = "MANUAL") -> dict:
        self._authorize(identity, pin)
        active = self.store.active_suppression(int(serid))
        if active is None:
            raise RuntimeError("suppression detector tidak aktif")
        return self._end_suppression(
            active.suppression_id, at=self.now(), reason=reason, ended_by=identity.username, identity=identity,
        )

    def _end_suppression(self, suppression_id: str, *, at: datetime, reason: str,
                         ended_by: str, identity) -> dict:
        """End once and atomically retain the lifecycle and in-flight uncertainty audit."""
        db = self.security._connection()
        try:
            self.store._begin(db)
            current = self.store.get_suppression(str(suppression_id), connection=db)
            if current is None:
                raise RuntimeError("suppression tidak ditemukan")
            ended, changed = self.store.end_suppression(
                str(suppression_id), at, reason, ended_by=ended_by,
                cancel_source_silences=True, connection=db,
            )
            result = asdict(ended) if ended is not None else asdict(current)
            states = {
                str(row[0]) for row in db.execute(
                    "SELECT source_silence_state FROM remote_alarm_state WHERE suppression_id=?",
                    (str(suppression_id),),
                ).fetchall() if row[0]
            }
            result["source_silence_state"] = next(
                (state for state in ("UNCERTAIN", "FAILED", "RECONCILING", "PENDING", "DISPATCHING", "CANCELLED", "RECONCILED", "CONFIRMED") if state in states),
                "NONE",
            )
            if changed:
                self.audit.record(
                    "ALARM_SUPPRESSION_END", identity, "station", str(current.serid),
                    before=asdict(current), after=result, source="central", connection=db,
                )
                if "UNCERTAIN" in states:
                    self.audit.record(
                        "SUPPRESSION_SOURCE_SILENCE_UNCERTAIN", identity, "station", str(current.serid),
                        success=False,
                        reason="remote silence began before suppression ended; outcome cannot be proven",
                        source="central", connection=db,
                    )
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def cancel(self, identity, pin: str, suppression_id: str, reason: str) -> dict:
        self._authorize(identity, pin)
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValueError("Alasan pembatalan suppression wajib diisi")
        return self._end_suppression(
            str(suppression_id), at=self.now(), reason=f"CANCELLED: {reason_text}",
            ended_by=identity.username, identity=identity,
        )

    def expire_due(self) -> int:
        now = self.now()
        expired = 0
        for item in self.store.due_suppressions(now):
            result = self._end_suppression(
                item.suppression_id, at=now, reason="EXPIRED", ended_by="system", identity=None,
            )
            if result.get("ended_reason") == "EXPIRED":
                expired += 1
        return expired
