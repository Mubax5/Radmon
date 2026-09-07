from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import Settings

LOGGER=logging.getLogger(__name__)


class SyncAgent:
    def __init__(self, repository: Any, settings: Settings, *, client: Any | None = None) -> None:
        self.repository=repository; self.settings=settings; self.client=client or httpx.Client(timeout=settings.sync_timeout)

    def _payload(self, rows: list[dict[str,Any]]) -> dict[str,Any]:
        items=[]
        for row in rows:
            dt=row["dtom"]; dt_text=dt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(dt,"strftime") else str(dt)
            items.append({"sample_key":row["sample_key"],"serid":int(row["serid"]),"dtom":dt_text,"doserate":float(row["doserate"]),"previnterval":int(row.get("previnterval",2)),"stat":int(row.get("stat",0))})
        return {"source_name":f"Gd{self.settings.building}-{self.settings.room.replace(' ','')}","measurements":items}

    def run_once(self) -> int:
        rows=self.repository.pending_sync(self.settings.sync_batch_size)
        if not rows: return 0
        ids=[int(row["queueid"]) for row in rows]
        try:
            response=self.client.post(self.settings.central_url.rstrip("/")+"/api/v1/measurements/batch",json=self._payload(rows),headers={"Authorization":f"Bearer {self.settings.central_token}"},timeout=self.settings.sync_timeout)
            response.raise_for_status(); self.repository.mark_sync_sent(ids); LOGGER.info("central sync sent=%s response=%s",len(ids),response.json()); return len(ids)
        except Exception as exc:
            self.repository.mark_sync_failed(ids,str(exc)); LOGGER.warning("central sync failed rows=%s error=%s",len(ids),exc); return 0

    def run_forever(self, interval: float=2.0) -> None:
        failure_streak=0
        while True:
            try:
                pending=self.repository.pending_sync(1)
                if not pending: failure_streak=0; time.sleep(interval); continue
                sent=self.run_once()
                if sent: failure_streak=0; time.sleep(0.1)
                else: failure_streak+=1; time.sleep(min(60.0,max(interval,2**min(failure_streak,6))))
            except KeyboardInterrupt: LOGGER.info("sync stopped by operator"); return
            except Exception as exc: failure_streak+=1; LOGGER.exception("sync loop error: %s",exc); time.sleep(min(60.0,2**min(failure_streak,6)))
