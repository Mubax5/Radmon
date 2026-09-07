from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import tempfile
import time
from typing import Any

import httpx

from .config import Settings
from .models import Measurement
from .repository import make_sample_key

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncCheckpointStore:
    path: Path

    def load(self) -> datetime | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            value = data.get("last_synced")
            return datetime.fromisoformat(value) if value else None
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save(self, value: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"last_synced": value.isoformat(timespec="seconds")}, ensure_ascii=False)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=self.path.parent, prefix="sync-", suffix=".tmp") as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(self.path)


class SyncAgent:
    def __init__(
        self,
        repository: Any,
        settings: Settings,
        *,
        checkpoint: SyncCheckpointStore | None = None,
        client: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.checkpoint = checkpoint or SyncCheckpointStore(settings.runtime_dir / f"sync-{settings.serid}.json")
        self.client = client or httpx.Client(timeout=settings.sync_timeout)

    def _starting_point(self) -> datetime:
        saved = self.checkpoint.load()
        if saved is not None:
            return saved
        return datetime.now() - timedelta(hours=max(0, self.settings.sync_initial_lookback_hours))

    def _payload(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        measurements = []
        for row in rows:
            dt = row["dtom"]
            measurement = Measurement(
                serid=int(row["serid"]),
                measured_at=dt,
                dose_rate=float(row["doserate"]),
                previnterval=int(row.get("previnterval") or 2),
                stat=int(row.get("stat") or 0),
            )
            measurements.append(
                {
                    "sample_key": make_sample_key(measurement),
                    "serid": measurement.serid,
                    "dtom": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "doserate": measurement.dose_rate,
                    "dose": float(row.get("dose") or 0.0),
                    "previnterval": measurement.previnterval,
                    "stat": measurement.stat,
                }
            )
        return {
            "source_name": f"Gd{self.settings.building}-{self.settings.room.replace(' ', '')}",
            "station": {
                "serid": self.settings.serid,
                "name": self.settings.room,
                "location": self.settings.location,
                "maxidlemin": self.settings.maxidlemin,
                "warnlevel": self.settings.warnlevel,
                "alarmlevel": self.settings.alarmlevel,
                "unit": self.settings.unit,
            },
            "measurements": measurements,
        }

    def run_once(self) -> int:
        if not self.settings.sync_enabled:
            return 0
        after = self._starting_point()
        rows = self.repository.measurements_after(after, serid=self.settings.serid, limit=self.settings.sync_batch_size)
        if not rows:
            return 0
        try:
            response = self.client.post(
                self.settings.central_url.rstrip("/") + "/api/v1/measurements/batch",
                json=self._payload(rows),
                headers={"Authorization": f"Bearer {self.settings.central_token}"},
                timeout=self.settings.sync_timeout,
            )
            response.raise_for_status()
            latest = max(row["dtom"] for row in rows)
            self.checkpoint.save(latest)
            LOGGER.info("central sync sent=%s through=%s", len(rows), latest)
            return len(rows)
        except Exception as exc:
            LOGGER.warning("central sync failed rows=%s error=%s", len(rows), exc)
            return 0

    def run_forever(self, stop_event: Any, interval: float = 2.0) -> None:
        while not stop_event.is_set():
            self.run_once()
            stop_event.wait(interval)
