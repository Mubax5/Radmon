from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class AlarmPolicyService:
    def __init__(self, store, audit, *, now: Callable[[], datetime] | None = None, projector=None) -> None:
        self.store = store
        self.audit = audit
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.projector = projector
        self.notifications_enabled = True

    @staticmethod
    def _measurement_time(row: dict[str, Any]) -> datetime:
        value = row.get("dtom", row.get("dtoa"))
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        raise ValueError("waktu pengukuran tidak valid")

    @staticmethod
    def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
        value = row.get(key)
        return default if value is None else float(value)

    def _snapshot(self, tx, *, underlying: str, measured_value: float | None = None,
                  threshold: float | None = None, active_event_id: str | None = None) -> dict[str, Any]:
        state = tx.state
        suppression = tx.active_suppression
        if suppression is not None:
            policy_state = "SUPPRESSED"
        elif state.retrigger_locked and state.active_event_id is None and underlying == "ALARM":
            policy_state = "RETRIGGER_LOCKED"
        elif underlying == "ALARM" and (active_event_id or state.active_event_id):
            policy_state = "ALARM"
        else:
            policy_state = underlying
        snapshot = {
            "serid": state.serid,
            "policy_state": policy_state,
            "underlying_dose_status": underlying,
            "trigger_count": state.trigger_count,
            "retrigger_locked": bool(state.retrigger_locked),
            "active_event_id": active_event_id if active_event_id is not None else state.active_event_id,
            "measured_value": measured_value,
            "threshold": threshold,
            "suppressed": suppression is not None,
            "suppression_id": suppression.suppression_id if suppression else None,
            "suppression_expires_at": suppression.expires_at if suppression else None,
            "suppression_pic": suppression.pic if suppression else None,
            "suppression_reason": suppression.reason if suppression else None,
        }
        if self.projector is not None:
            self.projector.project(snapshot)
        return snapshot

    def evaluate_live(self, row: dict[str, Any], *, source_id: str | None = None) -> dict[str, Any]:
        serid = int(row["serid"])
        measured_at = self._measurement_time(row)
        dose_rate = self._float(row, "doserate")
        warnlevel = self._float(row, "warnlevel")
        alarmlevel = self._float(row, "alarmlevel")
        is_normal = dose_rate < warnlevel
        is_alarm = dose_rate >= alarmlevel

        with self.store.detector_transaction(serid) as tx:
            state = tx.state
            suppression = tx.active_suppression

            if suppression is not None and measured_at >= suppression.expires_at:
                tx.end_suppression(suppression.suppression_id, measured_at, "EXPIRED")
                suppression = None

            if is_normal:
                tx.reset_policy(measured_at)
                if suppression and suppression.auto_resume_on_normal:
                    tx.end_suppression(suppression.suppression_id, measured_at, "AUTO_NORMAL")
                return self._snapshot(
                    tx, underlying="NORMAL", measured_value=dose_rate, threshold=alarmlevel
                )

            if suppression is not None:
                if is_alarm:
                    tx.create_suppressed_event(
                        suppression,
                        surfaced_at=measured_at,
                        measured_value=dose_rate,
                        threshold=alarmlevel,
                        source_id=source_id,
                    )
                return self._snapshot(
                    tx,
                    underlying="ALARM" if is_alarm else "ALERT",
                    measured_value=dose_rate,
                    threshold=alarmlevel,
                )

            if not is_alarm:
                return self._snapshot(
                    tx, underlying="ALERT", measured_value=dose_rate, threshold=alarmlevel
                )

            if state.retrigger_locked:
                return self._snapshot(
                    tx, underlying="ALARM", measured_value=dose_rate, threshold=alarmlevel,
                    active_event_id=None,
                )

            if state.active_event_id:
                return self._snapshot(
                    tx, underlying="ALARM", measured_value=dose_rate, threshold=alarmlevel
                )

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
                source_id=source_id,
            )
            state.trigger_count = next_index
            state.active_event_id = event.event_id
            state.last_trigger_at = measured_at
            if next_index == 3:
                state.retrigger_locked = True
            tx.save_state(state, at=measured_at)
            return self._snapshot(
                tx, underlying="ALARM", measured_value=dose_rate, threshold=alarmlevel,
                active_event_id=event.event_id,
            )

    def mark_event_responded(self, event_id: str, at: datetime, pic: str, action: str, reason: str):
        event = self.store.get_event(str(event_id))
        if event is None:
            raise RuntimeError("policy event tidak ditemukan")
        with self.store.detector_transaction(event.serid) as tx:
            responded = tx.respond_event(str(event_id), at, pic, action, reason)
            if tx.state.active_event_id == event_id:
                tx.state.active_event_id = None
                tx.save_state(at=at)
            return responded

    def list_events(self, *, serid: int | None = None, active_only: bool = False,
                    notify_pending_only: bool = False, limit: int = 500) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.store.list_policy_events(
            serid=serid, active_only=active_only,
            notify_pending_only=notify_pending_only, limit=limit,
        )]

    def get_policy(self, serid: int) -> dict[str, Any]:
        state = self.store.get_state(int(serid))
        suppression = self.store.active_suppression(int(serid))
        return {
            "serid": state.serid,
            "trigger_count": state.trigger_count,
            "retrigger_locked": state.retrigger_locked,
            "active_event_id": state.active_event_id,
            "window_started_at": state.window_started_at,
            "last_trigger_at": state.last_trigger_at,
            "last_normal_at": state.last_normal_at,
            "suppressed": suppression is not None,
            "suppression": asdict(suppression) if suppression else None,
        }

    def observe_source_alarm(self, source_id: str, row: dict[str, Any]) -> dict[str, Any]:
        serid = int(row["serid"])
        event_time = self._measurement_time(row)
        historical = bool(row.get("_historical_seed"))
        state = self.store.get_state(serid)
        suppression = self.store.active_suppression(serid)
        event = self.store.get_event(state.active_event_id) if state.active_event_id else None
        if historical:
            decision = "HISTORICAL_SEED"
            visible = False
        elif suppression is not None:
            decision = "SUPPRESSED"
            visible = False
        elif state.retrigger_locked and event is None:
            decision = "RETRIGGER_LOCKED"
            visible = False
        elif event is not None:
            decision = "SURFACED"
            visible = True
        else:
            decision = "COALESCED_DUPLICATE"
            visible = False
        self.store.annotate_raw_alarm(
            source_id,
            serid,
            event_time,
            policy_decision=decision,
            suppression_id=suppression.suppression_id if suppression else None,
            operator_visible=visible,
            policy_event_id=event.event_id if event else None,
        )
        return {
            "serid": serid,
            "source_id": source_id,
            "decision": decision,
            "policy_event_id": event.event_id if event else None,
            "operator_visible": visible,
        }

    def process_cycle(self, source_id: str, live_rows: list[dict[str, Any]], alarm_rows: list[dict[str, Any]]):
        before = {item.event_id for item in self.store.list_policy_events(limit=5000)}
        for row in live_rows:
            self.evaluate_live(row, source_id=source_id)
        for row in alarm_rows:
            self.observe_source_alarm(source_id, row)
        return [item for item in self.store.list_policy_events(limit=5000) if item.event_id not in before]

    def mark_notification_sent(self, event_id: str, at: datetime | None = None) -> None:
        self.store.mark_notification_sent(event_id, at or self.now())

    def restore_and_reconcile_current_state(self) -> None:
        self.notifications_enabled = False
