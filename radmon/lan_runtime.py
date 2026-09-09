from __future__ import annotations

from datetime import datetime
import logging
import os
import threading
from typing import Any
from zoneinfo import ZoneInfo

from .lan import LanAggregator, LanCheckpointStore, MariaCentralStore, RemoteMariaDBSource
from .quarters import Quarter, quarter_for, quarters_overlapping

LOGGER = logging.getLogger(__name__)


class LanRuntime:
    """Pull production LAN databases into central ipradmon and own archive rollover."""

    def __init__(
        self,
        settings,
        services,
        *,
        whatsapp_dispatcher: Any | None = None,
        archive_service: Any | None = None,
        archive_check_interval: float | None = None,
    ) -> None:
        self.settings = settings
        self.services = services
        self.whatsapp_dispatcher = whatsapp_dispatcher
        self.archive_service = archive_service
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.interval = max(0.5, float(os.getenv("RADMON_LAN_POLL_INTERVAL", "2")))
        self.batch_size = max(1, int(os.getenv("RADMON_LAN_BATCH_SIZE", "1000")))
        configured_archive_interval = getattr(settings, "archive_check_interval", 60.0)
        self.archive_check_interval = max(
            5.0,
            float(
                archive_check_interval
                if archive_check_interval is not None
                else os.getenv("RADMON_ARCHIVE_CHECK_INTERVAL", str(configured_archive_interval))
            ),
        )
        self.archive_timezone = str(getattr(settings, "archive_timezone", "Asia/Jakarta"))
        self.central = MariaCentralStore(settings)
        self.checkpoints = LanCheckpointStore(services.security)

    def _thread(self, name: str, target) -> None:
        thread = threading.Thread(name=name, target=target, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _aggregator(self) -> LanAggregator:
        return LanAggregator(
            self.central,
            self.checkpoints,
            remote_factory=lambda item: RemoteMariaDBSource(item),
            alarm_mirror=self.services.alarm_mirror,
            batch_size=self.batch_size,
        )

    def _run_source(self, source) -> None:
        aggregator = self._aggregator()
        while not self.stop_event.is_set():
            result = aggregator.run_source_once(source)
            if result.error:
                state = self.services.source_health.record_failure(source, result.error)
                LOGGER.warning(
                    "LAN source=%s host=%s state=%s error=%s",
                    source.source_id,
                    source.host,
                    state["state"],
                    result.error,
                )
            else:
                state = self.services.source_health.record_success(
                    source,
                    live=True,
                    alarm=True,
                    history=True,
                )
                if result.inserted_measurements or result.mirrored_alarms or state.get("transition_message"):
                    LOGGER.info(
                        "LAN source=%s host=%s state=%s measurements=%s alarms=%s",
                        source.source_id,
                        source.host,
                        state["state"],
                        result.inserted_measurements,
                        result.mirrored_alarms,
                    )
            self.stop_event.wait(self.interval)

    def _run_whatsapp(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.whatsapp_dispatcher.run_once()
            except Exception as exc:
                LOGGER.warning("WhatsApp dispatcher error=%s", exc)
            self.stop_event.wait(max(2.0, float(os.getenv("RADMON_WHATSAPP_INTERVAL", "20"))))

    def _archive_candidates(self, now: datetime) -> list[Quarter]:
        if self.archive_service is None:
            return []
        current = quarter_for(now, self.archive_timezone)
        candidates: dict[str, Quarter] = {}
        archive_store = getattr(self.archive_service, "store", None)
        oldest = archive_store.oldest_measurement_time() if archive_store is not None and hasattr(archive_store, "oldest_measurement_time") else None
        if isinstance(oldest, datetime):
            oldest_local = oldest.replace(tzinfo=ZoneInfo(self.archive_timezone)) if oldest.tzinfo is None else oldest.astimezone(ZoneInfo(self.archive_timezone))
            if oldest_local < current.start:
                for quarter in quarters_overlapping(oldest_local, current.start, self.archive_timezone):
                    if quarter.end <= current.start:
                        candidates[quarter.quarter_id] = quarter
        catalog = getattr(self.archive_service, "catalog", None)
        if catalog is not None:
            for item in catalog.list_archives(limit=1000):
                if item.get("state") == "COMPLETE":
                    continue
                quarter_id = str(item.get("quarter_id") or "")
                try:
                    year_text, number_text = quarter_id.split("-Q", 1)
                    anchor = datetime(
                        int(year_text),
                        (int(number_text) - 1) * 3 + 1,
                        1,
                        tzinfo=ZoneInfo(self.archive_timezone),
                    )
                    quarter = quarter_for(anchor, self.archive_timezone)
                except (ValueError, TypeError):
                    continue
                if quarter.end <= current.start:
                    candidates[quarter.quarter_id] = quarter
        return sorted(candidates.values(), key=lambda quarter: quarter.start)

    def _record_pending(self, quarter: Quarter, drain_info: dict[str, Any], reason: str) -> None:
        catalog = self.archive_service.catalog
        existing = catalog.get(quarter.quarter_id)
        if existing is None:
            catalog.store.upsert_archive(
                quarter_id=quarter.quarter_id,
                start_at=quarter.start.isoformat(),
                end_at=quarter.end.isoformat(),
                state="PENDING_DRAIN",
                drain=drain_info,
                last_error=reason,
            )
        else:
            catalog.store.update_archive_state(
                quarter.quarter_id,
                "PENDING_DRAIN",
                drain=drain_info,
                last_error=reason,
                increment_retry=True,
            )
        audit = getattr(self.services, "audit", None)
        if audit is not None:
            audit.record(
                "ARCHIVE_DRAIN_PENDING",
                None,
                "archive",
                quarter.quarter_id,
                after={"drain": drain_info},
                success=False,
                reason=reason,
                source="central",
            )

    def run_archive_check_once(self, now: datetime | None = None) -> str:
        if self.archive_service is None:
            return "DISABLED"
        current_time = now or datetime.now(ZoneInfo(self.archive_timezone))
        current = quarter_for(current_time, self.archive_timezone)
        candidates = self._archive_candidates(current_time)
        if not candidates:
            return "CURRENT"
        status = "CURRENT"
        for quarter in candidates:
            existing = self.archive_service.catalog.get(quarter.quarter_id)
            if existing and existing.get("state") in {"SEALED", "PURGING"}:
                self.archive_service.run_rollover(
                    quarter,
                    drain_info=dict(existing.get("drain") or {}),
                    active_quarter=current,
                )
                status = "COMPLETE"
                continue

            drain_info: dict[str, Any] = {}
            aggregator = self._aggregator()
            try:
                cutoff = quarter.end.replace(tzinfo=None)
                for source in self.services.sources.values():
                    drained = aggregator.drain_source_until(source, cutoff)
                    for serid, value in drained.items():
                        key = f"{source.source_id}:{int(serid)}"
                        drain_info[key] = value.isoformat() if isinstance(value, datetime) else None
            except Exception as exc:
                self._record_pending(quarter, drain_info, str(exc))
                LOGGER.warning("Quarter %s pending drain: %s", quarter.quarter_id, exc)
                return "PENDING_DRAIN"

            self.archive_service.run_rollover(
                quarter,
                drain_info=drain_info,
                active_quarter=current,
            )
            status = "COMPLETE"
        return status

    def _run_archive_lifecycle(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.run_archive_check_once()
            except Exception as exc:
                LOGGER.warning("Quarter archive lifecycle error=%s", exc)
            self.stop_event.wait(self.archive_check_interval)

    def start(self) -> None:
        for source in self.services.sources.values():
            self._thread(f"radmon-lan-{source.source_id}", lambda active=source: self._run_source(active))
        if self.whatsapp_dispatcher is not None:
            self._thread("radmon-whatsapp", self._run_whatsapp)
        if self.archive_service is not None:
            self._thread("radmon-quarter-archive", self._run_archive_lifecycle)
        LOGGER.info("LAN runtime started sources=%s interval=%ss", len(self.services.sources), self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3.0)
        LOGGER.info("LAN runtime stopped")
