from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import uuid
import zipfile
from typing import Any, Callable

from .archive import verify_archive

LOG = logging.getLogger(__name__)
_QUARTER = re.compile(r"[0-9]{4}-Q[1-4]\Z")
_YEAR = re.compile(r"[0-9]{4}\Z")


class ArchiveExportJobs:
    """Durable asynchronous merge of immutable quarterly SQL archive bundles."""

    def __init__(self, security, catalog, archive_dir: Path | str) -> None:
        self.security = security
        self.catalog = catalog
        self.archive_root = Path(archive_dir).resolve()
        self.artifact_dir = self.archive_root / "exports"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radmon-archive-export")
        self._ensure_schema()
        self._recover_jobs()

    def _ensure_schema(self) -> None:
        with self.security._connection() as connection:
            connection.execute("""
CREATE TABLE IF NOT EXISTS archive_export_jobs (
 job_id TEXT PRIMARY KEY, username TEXT NOT NULL, selection TEXT NOT NULL,
  selection_value TEXT, quarter_ids TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'queued',
 partitions_total INTEGER NOT NULL, partitions_read INTEGER NOT NULL DEFAULT 0,
 rows_read INTEGER NOT NULL DEFAULT 0, bytes_written INTEGER NOT NULL DEFAULT 0,
 artifact_name TEXT, error TEXT, created_at TEXT NOT NULL, completed_at TEXT
)""")

    def _recover_jobs(self) -> None:
        with self.security._connection() as connection:
            connection.execute("UPDATE archive_export_jobs SET status='failed', error=?, completed_at=? WHERE status='running'",
                               ("proses export terhenti saat layanan dimulai ulang", self._now()))
            rows = connection.execute("SELECT job_id FROM archive_export_jobs WHERE status='queued'").fetchall()
        for (job_id,) in rows:
            self._executor.submit(self._generate, str(job_id), lambda _item: None)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _item(row: tuple[Any, ...]) -> dict[str, Any]:
        fields = ("job_id", "username", "selection", "selection_value", "quarter_ids", "status", "phase",
                  "partitions_total", "partitions_read", "rows_read", "bytes_written", "artifact_name",
                  "error", "created_at", "completed_at")
        result = dict(zip(fields, row))
        result["quarter_ids"] = json.loads(result["quarter_ids"])
        return result

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            return None
        with self.security._connection() as connection:
            row = connection.execute("SELECT job_id, username, selection, selection_value, quarter_ids, status, phase, partitions_total, partitions_read, rows_read, bytes_written, artifact_name, error, created_at, completed_at FROM archive_export_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._item(row) if row else None

    def list(self, *, username: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT job_id, username, selection, selection_value, quarter_ids, status, phase, partitions_total, partitions_read, rows_read, bytes_written, artifact_name, error, created_at, completed_at FROM archive_export_jobs"
        params: tuple[Any, ...] = ()
        if username is not None:
            query += " WHERE username=?"
            params = (username.strip().lower(),)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self.security._connection() as connection:
            rows = connection.execute(query, params + (max(1, min(int(limit), 100)),)).fetchall()
        return [self._item(row) for row in rows]

    def inventory(self) -> dict[str, Any]:
        items = self.catalog.list_archives(limit=100000)
        counts: dict[str, int] = {}
        visible = []
        for item in items:
            quarter = str(item.get("quarter_id") or "")
            if _QUARTER.fullmatch(quarter):
                counts[quarter[:4]] = counts.get(quarter[:4], 0) + 1
                visible.append({key: item.get(key) for key in ("quarter_id", "state", "start_at", "end_at", "created_at", "updated_at", "row_counts")})
        return {"years": [{"year": int(year), "archive_count": count} for year, count in sorted(counts.items(), reverse=True)],
                "archives": visible}

    def select_archives(self, selection: str, value: str | None = None) -> list[dict[str, Any]]:
        items = self.catalog.list_archives(limit=100000)
        if selection == "all":
            selected = [item for item in items if str(item.get("state", "")).upper() == "COMPLETE"]
        elif selection == "year" and value and _YEAR.fullmatch(value):
            selected = [item for item in items if str(item.get("state", "")).upper() == "COMPLETE" and str(item.get("quarter_id", "")).startswith(value + "-")]
        elif selection == "single" and value and _QUARTER.fullmatch(value):
            selected = [item for item in items if item.get("quarter_id") == value and str(item.get("state", "")).upper() == "COMPLETE"]
        else:
            raise ValueError("pilihan arsip tidak valid")
        selected.sort(key=lambda item: str(item.get("quarter_id")))
        if selection == "single" and not selected:
            raise ValueError("arsip COMPLETE tidak ditemukan")
        if not selected:
            raise ValueError("tidak ada arsip COMPLETE untuk pilihan ini")
        return selected

    def create(self, identity, *, selection: str, value: str | None) -> dict[str, Any]:
        archives = self.select_archives(selection, value)
        job_id = uuid.uuid4().hex
        with self.security._connection() as connection:
            connection.execute("INSERT INTO archive_export_jobs(job_id,username,selection,selection_value,quarter_ids,status,partitions_total,created_at) VALUES(?,?,?,?,?,'queued',?,?)",
                               (job_id, identity.username.strip().lower(), selection, value, json.dumps([str(a["quarter_id"]) for a in archives]), len(archives), self._now()))
        job = self.get(job_id)
        self._executor.submit(self._generate, job_id, lambda _item: None)
        return job

    def _update(self, job_id: str, *, status: str | None = None, partitions_read: int | None = None,
                rows_read: int | None = None, bytes_written: int | None = None,
                artifact_name: str | None = None, error: str | None = None,
                phase: str | None = None) -> dict[str, Any]:
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        partitions_read = max(current["partitions_read"], partitions_read if partitions_read is not None else current["partitions_read"])
        rows_read = max(current["rows_read"], rows_read if rows_read is not None else current["rows_read"])
        bytes_written = max(current["bytes_written"], bytes_written if bytes_written is not None else current["bytes_written"])
        next_status = status or current["status"]
        completed = self._now() if next_status in {"completed", "failed"} else None
        with self.security._connection() as connection:
            connection.execute("UPDATE archive_export_jobs SET status=?,phase=?,partitions_read=?,rows_read=?,bytes_written=?,artifact_name=?,error=?,completed_at=? WHERE job_id=?",
                               (next_status, phase or current["phase"], partitions_read, rows_read, bytes_written, artifact_name, error, completed, job_id))
        return self.get(job_id)

    def _safe_source(self, item: dict[str, Any]) -> Path:
        quarter = str(item.get("quarter_id") or "")
        if not _QUARTER.fullmatch(quarter):
            raise ValueError("quarter archive tidak valid")
        expected = (self.archive_root / quarter[:4] / f"radmon-{quarter}.zip").resolve()
        try:
            expected.relative_to(self.archive_root)
        except ValueError as exc:
            raise ValueError("archive path berada di luar direktori arsip") from exc
        recorded = Path(str(item.get("archive_path") or "")).resolve()
        if recorded != expected or not expected.is_file():
            raise ValueError("lokasi archive tidak valid atau file hilang")
        return expected

    def _safe_artifact_dir(self) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        resolved = self.artifact_dir.resolve()
        if resolved != self.artifact_dir or resolved.parent != self.archive_root:
            raise ValueError("direktori hasil export tidak valid")
        return resolved

    def _generate(self, job_id: str, progress: Callable[[dict[str, Any]], None]) -> None:
        self._update(job_id, status="running")
        temp: Path | None = None
        try:
            job = self.get(job_id)
            records = {str(item.get("quarter_id")): item for item in self.catalog.list_archives(limit=100000)}
            artifact_dir = self._safe_artifact_dir()
            destination = artifact_dir / f"radmon-archive-{job_id}.sql"
            temp = destination.with_suffix(".sql.tmp")
            bytes_written = rows_read = partitions_read = 0
            last_progress_bytes = last_progress_rows = 0
            with temp.open("w", encoding="utf-8", newline="\n") as output:
                header = "-- RadMon merged archive SQL export; import into a compatible MariaDB schema.\nSTART TRANSACTION;\n"
                output.write(header)
                bytes_written += len(header.encode("utf-8"))
                progress(self._update(job_id, bytes_written=bytes_written))
                for quarter_index, quarter in enumerate(job["quarter_ids"]):
                    item = records.get(quarter)
                    if item is None or str(item.get("state", "")).upper() != "COMPLETE":
                        raise ValueError(f"archive {quarter} tidak COMPLETE")
                    source = self._safe_source(item)
                    self._update(job_id, phase=f"verifying:{quarter}")
                    verified = verify_archive(source)
                    if verified.get("quarter_id") != quarter:
                        raise ValueError(f"archive {quarter} tidak cocok")
                    with zipfile.ZipFile(source) as bundle:
                        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
                        member = f"radmon-{quarter}.sql"
                        if manifest.get("quarter_id") != quarter or member not in bundle.namelist() or bundle.testzip():
                            raise ValueError(f"archive {quarter} rusak atau tidak cocok")
                        with bundle.open(member) as sql:
                            self._update(job_id, phase=f"merging:{quarter}")
                            for raw_line in sql:
                                line = raw_line.decode("utf-8")
                                stripped = line.strip()
                                if not stripped or stripped.upper() in {"START TRANSACTION;", "COMMIT;"}:
                                    continue
                                # Each quarterly dump contains the full device snapshot. Keep one copy.
                                if quarter_index and stripped.upper().startswith("INSERT INTO DEVICE "):
                                    continue
                                output.write(line)
                                encoded = len(raw_line)
                                bytes_written += encoded
                                if stripped.upper().startswith("INSERT INTO "):
                                    rows_read += 1
                                if rows_read - last_progress_rows >= 1000 or bytes_written - last_progress_bytes >= 1024 * 1024:
                                    progress(self._update(job_id, partitions_read=partitions_read, rows_read=rows_read, bytes_written=bytes_written))
                                    last_progress_bytes, last_progress_rows = bytes_written, rows_read
                    partitions_read += 1
                    progress(self._update(job_id, partitions_read=partitions_read, rows_read=rows_read, bytes_written=bytes_written))
                ending = "COMMIT;\n"
                output.write(ending)
                bytes_written += len(ending.encode("utf-8"))
                output.flush()
                output.close()
            temp.replace(destination)
            self._update(job_id, status="completed", partitions_read=partitions_read, rows_read=rows_read,
                         bytes_written=bytes_written, artifact_name=destination.name, phase="completed")
        except Exception:
            LOG.exception("archive export failed job_id=%s", job_id)
            if temp is not None:
                temp.unlink(missing_ok=True)
            self._update(job_id, status="failed", error="penggabungan archive gagal", phase="failed")

    def artifact(self, job_id: str) -> tuple[dict[str, Any], Path]:
        item = self.get(job_id)
        if item is None:
            raise KeyError("archive export tidak ditemukan")
        if item["status"] != "completed" or item["artifact_name"] != f"radmon-archive-{job_id}.sql":
            raise ValueError("archive export belum siap")
        artifact_dir = self._safe_artifact_dir()
        path = (artifact_dir / item["artifact_name"]).resolve()
        if path.parent != artifact_dir or not path.is_file():
            raise FileNotFoundError("file export tidak ditemukan")
        return item, path

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
