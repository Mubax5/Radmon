from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import uuid
from typing import Any

from .audit import AuditTrail
from .reports import ReportService


LOG = logging.getLogger(__name__)


class WebReportJobs:
    """Durable report metadata with bounded, asynchronous PDF generation."""

    MAX_RANGE = timedelta(days=366)
    _JOB_ID = re.compile(r"[0-9a-f]{32}\Z")

    def __init__(self, security, audit: AuditTrail, repository: Any, settings) -> None:
        self.security = security
        self.audit = audit
        self.repository = repository
        self.settings = settings
        self.report_root = Path(settings.report_dir).resolve()
        self.artifact_dir = self.report_root / "web"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radmon-report")
        self._ensure_schema()
        self._recover_pending_jobs()

    def _ensure_schema(self) -> None:
        with self.security._connection() as connection:
            connection.execute(
                """
CREATE TABLE IF NOT EXISTS web_report_jobs (
  job_id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  serid INTEGER NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  status TEXT NOT NULL,
  artifact_name TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT
)
"""
            )

    def _recover_pending_jobs(self) -> None:
        """Resume work that was queued before a clean process shutdown.

        A worker that was already running cannot be resumed safely because its
        partial PDF may be incomplete, so it is retained as a failed job.
        """
        with self.security._connection() as connection:
            queued = connection.execute(
                "SELECT job_id, serid, start_at, end_at FROM web_report_jobs WHERE status = 'queued'"
            ).fetchall()
            connection.execute(
                "UPDATE web_report_jobs SET status = 'failed', error = ?, completed_at = ? WHERE status = 'running'",
                ("pembuatan report terhenti saat layanan dimulai ulang", datetime.now(timezone.utc).isoformat()),
            )
        for job_id, serid, start_at, end_at in queued:
            try:
                self._executor.submit(
                    self._generate,
                    str(job_id),
                    int(serid),
                    datetime.fromisoformat(str(start_at)),
                    datetime.fromisoformat(str(end_at)),
                )
            except (TypeError, ValueError):
                self._set_status(job_id, "failed", error="metadata report tidak valid")

    @staticmethod
    def _item(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = ("job_id", "username", "serid", "start_at", "end_at", "status", "artifact_name", "error", "created_at", "completed_at")
        return dict(zip(keys, row))

    def list(self, *, username: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT job_id, username, serid, start_at, end_at, status, artifact_name, error, created_at, completed_at FROM web_report_jobs"
        params: tuple[Any, ...] = ()
        if username is not None:
            query += " WHERE username = ?"
            params = (username.strip().lower(),)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self.security._connection() as connection:
            rows = connection.execute(query, params + (max(1, min(int(limit), 500)),)).fetchall()
        return [self._item(row) for row in rows]

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not self._JOB_ID.fullmatch(job_id):
            return None
        with self.security._connection() as connection:
            row = connection.execute(
                "SELECT job_id, username, serid, start_at, end_at, status, artifact_name, error, created_at, completed_at FROM web_report_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._item(row) if row else None

    def create(self, identity, *, serid: int, start: datetime, end: datetime) -> dict[str, Any]:
        start = self._as_utc(start)
        end = self._as_utc(end)
        if end <= start:
            raise ValueError("report end must be after start")
        if end - start > self.MAX_RANGE:
            # Long-running reports are bounded independently of any client path.
            raise ValueError("rentang report terlalu panjang")
        if not self._station_exists(int(serid)):
            raise ValueError("station tidak ditemukan")
        job_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with self.security._connection() as connection:
            connection.execute(
                "INSERT INTO web_report_jobs (job_id, username, serid, start_at, end_at, status, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                (job_id, identity.username, int(serid), start.isoformat(), end.isoformat(), created_at),
            )
        item = self.get(job_id)
        if item is None:
            raise RuntimeError("report job tidak tersimpan")
        self.audit.record("REPORT_REQUEST", identity, "report", job_id, after={"serid": int(serid), "start_at": start, "end_at": end})
        self._executor.submit(self._generate, job_id, int(serid), start, end)
        return item

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _station_exists(self, serid: int) -> bool:
        stations = getattr(self.repository, "stations", None)
        if callable(stations):
            try:
                return any(int(item["serid"]) == serid for item in stations())
            except (KeyError, TypeError, ValueError):
                return False
        has_station = getattr(self.repository, "has_station", None)
        if callable(has_station):
            return bool(has_station(serid))
        try:
            station = self.repository.station_config(serid)
        except (KeyError, ValueError):
            return False
        return int(getattr(station, "serid", -1)) == serid

    def _safe_artifact_dir(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        directory = self.artifact_dir.resolve()
        try:
            directory.relative_to(self.report_root)
        except ValueError as exc:
            raise ValueError("direktori artifact report tidak valid") from exc
        return directory

    def _generate(self, job_id: str, serid: int, start: datetime, end: datetime) -> None:
        self._set_status(job_id, "running")
        try:
            artifact_dir = self._safe_artifact_dir()
            name = f"radmon-{job_id}.pdf"
            destination = (artifact_dir / name).resolve()
            destination.relative_to(artifact_dir)
            ReportService(self.repository, replace(self.settings, serid=serid)).export_pdf(start, end, destination)
        except Exception as exc:
            LOG.exception("web report generation failed job_id=%s", job_id)
            self._set_status(job_id, "failed", error="pembuatan report gagal")
            return
        self._set_status(job_id, "completed", artifact_name=name)

    def _set_status(self, job_id: str, status: str, *, artifact_name: str | None = None, error: str | None = None) -> None:
        completed_at = datetime.now(timezone.utc).isoformat() if status in {"completed", "failed"} else None
        with self.security._connection() as connection:
            connection.execute(
                "UPDATE web_report_jobs SET status = ?, artifact_name = ?, error = ?, completed_at = ? WHERE job_id = ?",
                (status, artifact_name, error, completed_at, job_id),
            )

    def artifact(self, job_id: str) -> tuple[dict[str, Any], Path]:
        item = self.get(job_id)
        if item is None:
            raise KeyError("report job tidak ditemukan")
        if item["status"] != "completed" or not item["artifact_name"]:
            raise ValueError("report belum siap")
        expected_name = f"radmon-{job_id}.pdf"
        if item["artifact_name"] != expected_name:
            raise ValueError("artifact report tidak valid")
        artifact_dir = self._safe_artifact_dir()
        path = (artifact_dir / expected_name).resolve()
        try:
            path.relative_to(artifact_dir)
        except ValueError as exc:
            raise ValueError("artifact report tidak valid") from exc
        if not path.is_file():
            raise FileNotFoundError("artifact report tidak ditemukan")
        return item, path

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
