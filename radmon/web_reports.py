from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

from .audit import AuditTrail
from .reports import ReportService


LOG = logging.getLogger(__name__)


class _ReportJobCancelled(RuntimeError):
    pass


class WebReportJobs:
    """Durable report metadata with bounded, asynchronous PDF generation."""

    MAX_RANGE = ReportService.MAX_RANGE
    MAX_PENDING_PER_USER = 4
    _JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
    _IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
    REPORT_TIMEZONE = "Asia/Jakarta"
    REPORT_FORMAT = "pdf"
    GENERATOR_VERSION = "1"

    def __init__(self, security, audit: AuditTrail, repository: Any, settings, *, summary_reader=None) -> None:
        self.security = security
        self.audit = audit
        self.repository = repository
        self.settings = settings
        self.summary_reader = summary_reader
        self.report_root = Path(settings.report_dir).resolve()
        self.artifact_dir = self.report_root / "web"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radmon-report")
        self._shutdown_event = threading.Event()
        self._shutdown_started = False
        self._futures: dict[str, Any] = {}
        self._futures_lock = threading.Lock()
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
  completed_at TEXT,
  idempotency_key TEXT,
  request_fingerprint TEXT,
  report_timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
  report_format TEXT NOT NULL DEFAULT 'pdf',
  generator_version TEXT NOT NULL DEFAULT '1'
)
"""
            )
            # The report table predates durable request identities.  Keep this
            # additive so an existing operator database can be upgraded in
            # place without touching its job history or artifacts.
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(web_report_jobs)").fetchall()
            }
            additions = (
                ("idempotency_key", "TEXT"),
                ("request_fingerprint", "TEXT"),
                ("report_timezone", "TEXT NOT NULL DEFAULT 'Asia/Jakarta'"),
                ("report_format", "TEXT NOT NULL DEFAULT 'pdf'"),
                ("generator_version", "TEXT NOT NULL DEFAULT '1'"),
            )
            for name, definition in additions:
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE web_report_jobs ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                """
CREATE UNIQUE INDEX IF NOT EXISTS idx_web_report_jobs_owner_idempotency
ON web_report_jobs (username, idempotency_key)
WHERE idempotency_key IS NOT NULL
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
                self._submit(
                    str(job_id), int(serid),
                    datetime.fromisoformat(str(start_at)), datetime.fromisoformat(str(end_at)),
                )
            except (TypeError, ValueError):
                self._set_status(job_id, "failed", error="metadata report tidak valid")

    def _submit(self, job_id: str, serid: int, start: datetime, end: datetime) -> None:
        if self._shutdown_started:
            raise RuntimeError("worker report sedang berhenti")
        future = self._executor.submit(self._generate, job_id, serid, start, end)
        if future is not None:
            with self._futures_lock:
                self._futures[job_id] = future
                if getattr(future, "done", lambda: False)():
                    self._futures.pop(job_id, None)

    @staticmethod
    def _item(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = (
            "job_id", "username", "serid", "start_at", "end_at", "status",
            "artifact_name", "error", "created_at", "completed_at",
            "idempotency_key", "request_fingerprint", "report_timezone",
            "report_format", "generator_version",
        )
        return dict(zip(keys, row))

    @classmethod
    def _select_columns(cls) -> str:
        return (
            "job_id, username, serid, start_at, end_at, status, artifact_name, "
            "error, created_at, completed_at, idempotency_key, request_fingerprint, "
            "report_timezone, report_format, generator_version"
        )

    def list(self, *, username: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = f"SELECT {self._select_columns()} FROM web_report_jobs"
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
                f"SELECT {self._select_columns()} FROM web_report_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._item(row) if row else None

    @classmethod
    def _normalise_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = str(value).strip()
        if not cls._IDEMPOTENCY_KEY.fullmatch(key):
            raise ValueError("idempotency key report tidak valid")
        return key

    @classmethod
    def _request_fingerprint(cls, *, serid: int, start: datetime, end: datetime) -> str:
        canonical = {
            "serid": int(serid),
            "start_at": start.isoformat(timespec="microseconds"),
            "end_at": end.isoformat(timespec="microseconds"),
            "timezone": cls.REPORT_TIMEZONE,
            "format": cls.REPORT_FORMAT,
            "generator_version": cls.GENERATOR_VERSION,
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def create(
        self,
        identity,
        *,
        serid: int,
        start: datetime,
        end: datetime,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        start = self._as_utc(start)
        end = self._as_utc(end)
        ReportService.validate_range(start, end)
        if not self._station_exists(int(serid)):
            raise ValueError("station tidak ditemukan")
        idempotency_key = self._normalise_idempotency_key(idempotency_key)
        fingerprint = self._request_fingerprint(serid=int(serid), start=start, end=end)
        username = identity.username.strip().lower()
        job_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        # A known idempotent retry must return its durable terminal result even
        # if the source count has changed since the original request.  New
        # keys still preflight before any job row or artifact is created.
        if idempotency_key is not None:
            with self.security._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    f"SELECT {self._select_columns()} FROM web_report_jobs "
                    "WHERE username = ? AND idempotency_key = ?",
                    (username, idempotency_key),
                ).fetchone()
                if existing is not None:
                    item = self._item(existing)
                    if item.get("request_fingerprint") != fingerprint:
                        raise ValueError("idempotency key report sudah dipakai untuk pilihan lain")
                    return item
        ReportService(self.repository, replace(self.settings, serid=int(serid)), summary_reader=self.summary_reader).preflight(start, end)
        with self.security._connection() as connection:
            # BEGIN IMMEDIATE makes the pending-count guard and the unique
            # idempotency lookup one durable transaction.  Without it, two
            # browser tabs can both pass the count and enqueue duplicate PDFs.
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = connection.execute(
                    f"SELECT {self._select_columns()} FROM web_report_jobs "
                    "WHERE username = ? AND idempotency_key = ?",
                    (username, idempotency_key),
                ).fetchone()
                if existing is not None:
                    item = self._item(existing)
                    if item.get("request_fingerprint") != fingerprint:
                        raise ValueError("idempotency key report sudah dipakai untuk pilihan lain")
                    return item
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM web_report_jobs WHERE username = ? AND status IN ('queued', 'running')",
                (username,),
            ).fetchone()[0])
            if pending >= self.MAX_PENDING_PER_USER:
                raise ValueError("terlalu banyak report yang masih berjalan")
            try:
                connection.execute(
                    """
INSERT INTO web_report_jobs
  (job_id, username, serid, start_at, end_at, status, created_at,
   idempotency_key, request_fingerprint, report_timezone, report_format,
   generator_version)
VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
""",
                    (
                        job_id, username, int(serid), start.isoformat(), end.isoformat(),
                        created_at, idempotency_key, fingerprint, self.REPORT_TIMEZONE,
                        self.REPORT_FORMAT, self.GENERATOR_VERSION,
                    ),
                )
            except sqlite3.IntegrityError:
                # The partial unique index is the final race guard for older
                # SQLite builds or callers that entered between the lookup and
                # insert.  Return the already committed, matching request.
                if idempotency_key is None:
                    raise
                existing = connection.execute(
                    f"SELECT {self._select_columns()} FROM web_report_jobs "
                    "WHERE username = ? AND idempotency_key = ?",
                    (username, idempotency_key),
                ).fetchone()
                if existing is None:
                    raise
                item = self._item(existing)
                if item.get("request_fingerprint") != fingerprint:
                    raise ValueError("idempotency key report sudah dipakai untuk pilihan lain")
                return item
        item = self.get(job_id)
        if item is None:
            raise RuntimeError("report job tidak tersimpan")
        self.audit.record("REPORT_REQUEST", identity, "report", job_id, after={"serid": int(serid), "start_at": start, "end_at": end})
        try:
            self._submit(job_id, int(serid), start, end)
        except RuntimeError as exc:
            self._set_status(job_id, "failed", error="worker report tidak tersedia")
            raise RuntimeError("worker report tidak tersedia") from exc
        return item

    def preview_pdf(self, *, serid: int, start: datetime, end: datetime) -> bytes:
        start = self._as_utc(start)
        end = self._as_utc(end)
        ReportService.validate_range(start, end)
        if not self._station_exists(int(serid)):
            raise ValueError("station tidak ditemukan")
        return ReportService(
            self.repository,
            replace(self.settings, serid=int(serid)),
            summary_reader=self.summary_reader,
        ).pdf_bytes(start, end, preview=True)

    def validate_preview(self, *, serid: int, start: datetime, end: datetime) -> None:
        """Validate a draft preview request without generating a PDF body."""
        start = self._as_utc(start)
        end = self._as_utc(end)
        if not self._station_exists(int(serid)):
            raise ValueError("station tidak ditemukan")
        service = ReportService(
            self.repository,
            replace(self.settings, serid=int(serid)),
            summary_reader=self.summary_reader,
        )
        service.preflight(start, end)

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
        # Multiple service instances can recover the same queued row after a
        # restart.  Claiming in SQLite makes generation a one-worker action,
        # so only the claimant can publish the one canonical artifact.
        if not self._claim_job(job_id):
            with self._futures_lock:
                self._futures.pop(job_id, None)
            return
        temp: Path | None = None
        try:
            if self._shutdown_event.is_set():
                raise _ReportJobCancelled()
            artifact_dir = self._safe_artifact_dir()
            name = f"radmon-{job_id}.pdf"
            raw_destination = artifact_dir / name
            if raw_destination.is_symlink():
                raise ValueError("artifact report tidak valid")
            destination = raw_destination.resolve()
            destination.relative_to(artifact_dir)
            content = ReportService(
                self.repository,
                replace(self.settings, serid=serid),
                summary_reader=self.summary_reader,
            ).pdf_bytes(start, end)
            if self._shutdown_event.is_set():
                raise _ReportJobCancelled()
            temp = destination.with_suffix(".pdf.tmp")
            if temp.is_symlink():
                raise ValueError("artifact report tidak valid")
            with temp.open("wb") as handle:
                handle.write(content)
                handle.flush()
                import os
                os.fsync(handle.fileno())
            if self._shutdown_event.is_set():
                raise _ReportJobCancelled()
            temp.replace(destination)
        except _ReportJobCancelled:
            self._set_status(job_id, "failed", error="pembuatan report dibatalkan saat shutdown")
            return
        except ValueError as exc:
            LOG.exception("web report generation failed job_id=%s", job_id)
            self._set_status(job_id, "failed", error=str(exc)[:500] or "pembuatan report gagal")
            return
        except Exception as exc:
            LOG.exception("web report generation failed job_id=%s", job_id)
            self._set_status(job_id, "failed", error="pembuatan report gagal")
            return
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
            with self._futures_lock:
                self._futures.pop(job_id, None)
        self._set_status(job_id, "completed", artifact_name=name)

    def _claim_job(self, job_id: str) -> bool:
        with self.security._connection() as connection:
            result = connection.execute(
                "UPDATE web_report_jobs SET status = 'running', error = NULL WHERE job_id = ? AND status = 'queued'",
                (job_id,),
            )
            return result.rowcount == 1

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
        raw_path = artifact_dir / expected_name
        if raw_path.is_symlink():
            raise ValueError("artifact report tidak valid")
        path = raw_path.resolve()
        try:
            path.relative_to(artifact_dir)
        except ValueError as exc:
            raise ValueError("artifact report tidak valid") from exc
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("artifact report tidak ditemukan")
        return item, path

    def shutdown(self, timeout: float = 15.0) -> None:
        """Cancel queued work, checkpoint active work, and wait boundedly.

        Queued rows remain durable and are resumed by ``_recover_pending_jobs``
        after a restart. Active jobs publish only complete PDFs through a rename;
        cancellation removes their temporary file and records a terminal state.
        """
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._shutdown_event.set()
        with self._futures_lock:
            futures = list(self._futures.values())
        for future in futures:
            if hasattr(future, "cancel"):
                future.cancel()
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # small test doubles / older Python
            self._executor.shutdown(wait=False)
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            with self._futures_lock:
                active = bool(self._futures)
            if not active:
                break
            time.sleep(0.01)
        with self._futures_lock:
            active = bool(self._futures)
        if active:
            LOG.warning("report workers did not stop within %.1fs", max(0.1, float(timeout)))
