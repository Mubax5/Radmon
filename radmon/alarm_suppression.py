from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Callable

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

            suppression = self.store.start_suppression(
                int(serid),
                started_at,
                expires_at,
                bool(auto_resume_on_normal),
                pic_text,
                reason_text,
                identity.username,
                connection=tx.connection,
            )
            tx.active_suppression = suppression

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
        return [
            asdict(item)
            for item in self.store.list_suppressions(
                active_only=bool(active_only), limit=max(1, int(limit))
            )
        ]

    def end(self, identity, pin: str, serid: int, *, reason: str = "MANUAL") -> dict:
        self._authorize(identity, pin)
        active = self.store.active_suppression(int(serid))
        if active is None:
            raise RuntimeError("suppression detector tidak aktif")
        ended = self.store.end_suppression(active.suppression_id, self.now(), reason)
        result = asdict(ended) if ended is not None else asdict(active)
        self.audit.record(
            "ALARM_SUPPRESSION_END",
            identity,
            "station",
            str(int(serid)),
            after=result,
            source="central",
        )
        return result
