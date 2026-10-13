from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import shutil
import threading
import time
import uuid
import zipfile
from typing import Any, Callable

from .archive import MAX_ARCHIVE_MEMBER_BYTES, verify_archive
from .archive_store import TABLE_COLUMNS

LOG = logging.getLogger(__name__)


class _ArchiveExportCancelled(RuntimeError):
    pass
_QUARTER = re.compile(r"[0-9]{4}-Q[1-4]\Z")
_YEAR = re.compile(r"[0-9]{4}\Z")
MAX_EXPORT_PARTITIONS = 100
# These are bounded for a local, already-retained archive export rather than
# an untrusted upload.  Q1-Q3 are approximately 13.6M/22.3M/37.6M rows and
# their merged SQL is about 10 GiB; the former 5M/512 MiB limits stopped a
# valid job after it had already written a partial file.
MAX_EXPORT_ROWS = 100_000_000
MAX_EXPORT_BYTES = 16 * 1024 * 1024 * 1024
MAX_SQL_LINE_BYTES = 1024 * 1024
PAYLOAD_VERIFIER_VERSION = "streaming-archive-v2"

_EXPORTABLE_STATES = frozenset({"COMPLETE", "SEALED", "PURGING", "PENDING_DRAIN"})
_LEGACY_SIZE_VALIDATION_ERRORS = frozenset({
    "member archive terlalu besar",
    "payload archive terlalu besar",
})


def _insert_table(statement: str) -> str | None:
    match = re.match(
        r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        statement,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _has_one_terminator(statement: str) -> bool:
    """Reject a second SQL statement while allowing semicolons in strings."""
    in_string = False
    positions: list[int] = []
    index = 0
    while index < len(statement):
        char = statement[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == "'":
                if index + 1 < len(statement) and statement[index + 1] == "'":
                    index += 2
                    continue
                in_string = False
        elif char == "'":
            in_string = True
        elif char == ";":
            positions.append(index)
        index += 1
    return (
        not in_string
        and len(positions) == 1
        and not statement[positions[0] + 1:].strip()
    )


class ArchiveExportJobs:
    """Durable asynchronous merge of immutable quarterly SQL archive bundles."""

    def __init__(self, security, catalog, archive_dir: Path | str) -> None:
        self.security = security
        self.catalog = catalog
        self.archive_root = Path(archive_dir).resolve()
        self.artifact_dir = self.archive_root / "exports"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radmon-archive-export")
        self._shutdown_event = threading.Event()
        self._shutdown_started = False
        self._futures: dict[str, Any] = {}
        self._futures_lock = threading.Lock()
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
                               ("export terhenti saat layanan dimulai ulang; gunakan Coba lagi untuk memulai dari awal",
                                self._now()))
            rows = connection.execute(
                "SELECT job_id FROM archive_export_jobs WHERE status='queued' ORDER BY created_at LIMIT ?",
                (MAX_EXPORT_PARTITIONS,),
            ).fetchall()
        for (job_id,) in rows:
            self._submit(str(job_id), lambda _item: None)

    def _submit(self, job_id: str, progress: Callable[[dict[str, Any]], None]) -> None:
        if self._shutdown_started:
            raise RuntimeError("worker export sedang berhenti")
        future = self._executor.submit(self._generate, job_id, progress)
        if future is not None:
            with self._futures_lock:
                self._futures[job_id] = future
                if getattr(future, "done", lambda: False)():
                    self._futures.pop(job_id, None)

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
                integrity = (
                    self.catalog.payload_integrity(item)
                    if hasattr(self.catalog, "payload_integrity")
                    else {
                        "integrity_status": "UNVERIFIED",
                        "integrity_reason": "Bundle perlu verifikasi streaming sebelum ekspor.",
                        "integrity_verified_at": None,
                        "integrity_evidence_source": None,
                    }
                )
                visible.append({
                    **{key: item.get(key) for key in (
                        "quarter_id", "state", "start_at", "end_at", "created_at",
                        "updated_at", "row_counts", "last_error",
                    )},
                    **integrity,
                    # This only says that an explicit streaming preflight may
                    # be attempted; it does not claim a DAMAGED payload is
                    # valid.
                    "export_available": self._can_attempt_export(item),
                })
        return {"years": [{"year": int(year), "archive_count": count} for year, count in sorted(counts.items(), reverse=True)],
                "archives": visible}

    def select_archives(self, selection: str, value: str | None = None) -> list[dict[str, Any]]:
        items = self.catalog.list_archives(limit=100000)
        scoped: list[dict[str, Any]]
        if selection == "all":
            scoped = [item for item in items if _QUARTER.fullmatch(str(item.get("quarter_id") or ""))]
        elif selection == "year" and value and _YEAR.fullmatch(value):
            scoped = [item for item in items if str(item.get("quarter_id", "")).startswith(value + "-") and _QUARTER.fullmatch(str(item.get("quarter_id") or ""))]
        elif selection == "single" and value and _QUARTER.fullmatch(value):
            scoped = [item for item in items if item.get("quarter_id") == value]
        else:
            raise ValueError("pilihan arsip tidak valid")
        blocked = sorted(
            str(item.get("quarter_id") or "?")
            for item in scoped
            if not self._can_attempt_export(item)
        )
        if blocked:
            detail = ", ".join(blocked[:20])
            if len(blocked) > 20:
                detail += f" (+{len(blocked) - 20} lainnya)"
            raise ValueError(f"bundle terpilih belum aman untuk export: {detail}")
        selected = [item for item in scoped if self._can_attempt_export(item)]
        selected.sort(key=lambda item: str(item.get("quarter_id")))
        if selection == "single" and not selected:
            raise ValueError("arsip siap ekspor tidak ditemukan; bundle akan diverifikasi sebelum export")
        if not selected:
            raise ValueError("tidak ada bundle yang dapat diperiksa untuk pilihan ini")
        if len(selected) > MAX_EXPORT_PARTITIONS:
            raise ValueError(
                f"export archive melebihi batas {MAX_EXPORT_PARTITIONS} partisi; pilih tahun atau rentang lebih sempit"
            )
        return selected

    @classmethod
    def _can_attempt_export(cls, item: dict[str, Any]) -> bool:
        state = str(item.get("state") or "").upper()
        if not item.get("archive_path"):
            return False
        if state in _EXPORTABLE_STATES:
            return True
        # Q1-Q3 were marked DAMAGED solely by the old 512 MiB validator. A
        # fresh preflight remains mandatory, so a tampered bundle cannot pass
        # merely because its historical error had this wording.
        return state == "DAMAGED" and str(item.get("last_error") or "").strip() in _LEGACY_SIZE_VALIDATION_ERRORS

    def _preflight_archives(self, archives: list[dict[str, Any]]) -> None:
        """Verify archive integrity and resource bounds before queueing a job."""
        total_rows = 0
        total_sql_bytes = 0
        for item in archives:
            source = self._safe_source(item)
            manifest = verify_archive(source)
            quarter = str(item.get("quarter_id") or "")
            if str(manifest.get("quarter_id")) != quarter:
                raise ValueError(f"archive {quarter} tidak cocok")
            recorded_hash = str(item.get("archive_sha256") or "").strip().lower()
            if recorded_hash and recorded_hash != str(manifest.get("archive_sha256") or "").lower():
                raise ValueError(f"archive {quarter} checksum katalog berbeda")
            row_counts = manifest.get("row_counts") or {}
            total_rows += sum(
                int(value) for table, value in row_counts.items() if table in TABLE_COLUMNS
            )
            with zipfile.ZipFile(source) as bundle:
                member = f"radmon-{quarter}.sql"
                try:
                    info = bundle.getinfo(member)
                except KeyError as exc:
                    raise ValueError(f"archive {quarter} tidak memiliki SQL payload") from exc
                if int(info.file_size) > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError(f"archive {quarter} terlalu besar")
                total_sql_bytes += int(info.file_size)
            self._record_verified_payload(item, manifest, source, "streaming preflight")
        if total_rows > MAX_EXPORT_ROWS:
            raise ValueError(f"export archive melebihi batas {MAX_EXPORT_ROWS:,} row")
        if total_sql_bytes + 1024 * 1024 > MAX_EXPORT_BYTES:
            raise ValueError(f"export archive melebihi batas {MAX_EXPORT_BYTES:,} byte")
        artifact_dir = self._safe_artifact_dir()
        free = shutil.disk_usage(artifact_dir).free
        required = total_sql_bytes + 64 * 1024 * 1024
        if free < required:
            raise ValueError(
                f"ruang disk export tidak cukup: tersedia {free:,} byte, diperlukan sekitar {required:,} byte"
            )

    def _record_verified_payload(
        self,
        item: dict[str, Any],
        manifest: dict[str, Any],
        source: Path,
        evidence_source: str,
    ) -> None:
        recorder = getattr(self.catalog, "record_payload_verification", None)
        if not callable(recorder):
            return
        from .archive import _archive_manifest_identity

        identity = _archive_manifest_identity(source)
        recorder(
            str(item.get("quarter_id") or ""),
            archive_sha256=str(manifest.get("archive_sha256") or ""),
            row_counts=dict(manifest.get("row_counts") or {}),
            manifest_sha256=str(identity["manifest_sha256"]),
            member_crc=dict(identity["member_crc"]),
            verifier_version=PAYLOAD_VERIFIER_VERSION,
            evidence_source=evidence_source,
            verified_at=self._now(),
        )

    def create(self, identity, *, selection: str, value: str | None) -> dict[str, Any]:
        archives = self.select_archives(selection, value)
        self._preflight_archives(archives)
        job_id = uuid.uuid4().hex
        with self.security._connection() as connection:
            pending = int(connection.execute(
                "SELECT COUNT(*) FROM archive_export_jobs WHERE username=? AND status IN ('queued','running')",
                (identity.username.strip().lower(),),
            ).fetchone()[0])
            if pending >= 4:
                raise ValueError("terlalu banyak export archive yang masih berjalan")
            connection.execute("INSERT INTO archive_export_jobs(job_id,username,selection,selection_value,quarter_ids,status,partitions_total,created_at) VALUES(?,?,?,?,?,'queued',?,?)",
                               (job_id, identity.username.strip().lower(), selection, value, json.dumps([str(a["quarter_id"]) for a in archives]), len(archives), self._now()))
        job = self.get(job_id)
        self._submit(job_id, lambda _item: None)
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
        if current["status"] in {"completed", "failed"} and next_status != current["status"]:
            return current
        completed = self._now() if next_status in {"completed", "failed"} else None
        with self.security._connection() as connection:
            connection.execute("UPDATE archive_export_jobs SET status=?,phase=?,partitions_read=?,rows_read=?,bytes_written=?,artifact_name=?,error=?,completed_at=? WHERE job_id=?",
                               (next_status, phase or current["phase"], partitions_read, rows_read, bytes_written, artifact_name, error, completed, job_id))
        return self.get(job_id)

    def _claim(self, job_id: str) -> bool:
        """Atomically claim one queued job so restart/retry cannot duplicate it."""
        with self.security._connection() as connection:
            cursor = connection.execute(
                "UPDATE archive_export_jobs SET status='running', phase='starting', completed_at=NULL "
                "WHERE job_id=? AND status='queued'",
                (job_id,),
            )
            return cursor.rowcount == 1

    def retry(self, job_id: str, identity: Any) -> dict[str, Any]:
        """Queue a fresh job for an owned terminal failure; never resume a partial file."""
        item = self.get(job_id)
        if item is None:
            raise KeyError("archive export tidak ditemukan")
        username = str(getattr(identity, "username", "")).strip().lower()
        role = str(getattr(getattr(identity, "role", None), "value", getattr(identity, "role", "")))
        if item["username"] != username and role.casefold() != "administrator":
            raise PermissionError("archive export milik pengguna lain")
        if item["status"] != "failed":
            raise ValueError("hanya export gagal yang dapat diulang")
        return self.create(
            identity,
            selection=str(item["selection"]),
            value=item.get("selection_value"),
        )

    def _safe_source(self, item: dict[str, Any]) -> Path:
        quarter = str(item.get("quarter_id") or "")
        if not _QUARTER.fullmatch(quarter):
            raise ValueError("quarter archive tidak valid")
        raw_expected = self.archive_root / quarter[:4] / f"radmon-{quarter}.zip"
        if raw_expected.is_symlink():
            raise ValueError("archive symlink tidak diizinkan")
        expected = raw_expected.resolve()
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
        if not self._claim(job_id):
            return
        temp: Path | None = None
        try:
            if self._shutdown_event.is_set():
                raise _ArchiveExportCancelled()
            job = self.get(job_id)
            records = {str(item.get("quarter_id")): item for item in self.catalog.list_archives(limit=100000)}
            artifact_dir = self._safe_artifact_dir()
            destination = artifact_dir / f"radmon-archive-{job_id}.sql"
            # Never reuse a partial file left by another process/attempt.
            temp = artifact_dir / f".{destination.name}.{uuid.uuid4().hex}.tmp"
            bytes_written = rows_read = partitions_read = 0
            last_progress_bytes = last_progress_rows = 0
            with temp.open("wb") as output:
                header = b"-- RadMon merged archive SQL export; import into a compatible MariaDB schema.\nSTART TRANSACTION;\n"
                output.write(header)
                bytes_written += len(header)
                progress(self._update(job_id, bytes_written=bytes_written))
                baseline_device_lines: list[str] = []
                for quarter_index, quarter in enumerate(job["quarter_ids"]):
                    if self._shutdown_event.is_set():
                        raise _ArchiveExportCancelled()
                    item = records.get(quarter)
                    if item is None or not self._can_attempt_export(item):
                        raise ValueError(f"archive {quarter} belum siap untuk export")
                    source = self._safe_source(item)
                    self._update(job_id, phase=f"verifying:{quarter}")
                    verified = verify_archive(source)
                    if verified.get("quarter_id") != quarter:
                        raise ValueError(f"archive {quarter} tidak cocok")
                    recorded_hash = str(item.get("archive_sha256") or "").strip().lower()
                    if recorded_hash and recorded_hash != str(verified.get("archive_sha256") or "").lower():
                        raise ValueError(f"archive {quarter} checksum katalog berbeda")
                    self._record_verified_payload(item, verified, source, "streaming export worker")
                    expected_counts = {
                        str(table): int(value)
                        for table, value in dict(verified.get("row_counts") or {}).items()
                        if table in TABLE_COLUMNS
                    }
                    sql_counts = {table: 0 for table in TABLE_COLUMNS}
                    device_lines: list[str] = []
                    with zipfile.ZipFile(source) as bundle:
                        member = f"radmon-{quarter}.sql"
                        if member not in bundle.namelist():
                            raise ValueError(f"archive {quarter} rusak atau tidak cocok")
                        with bundle.open(member) as sql:
                            self._update(job_id, phase=f"merging:{quarter}")
                            for raw_line in sql:
                                if self._shutdown_event.is_set():
                                    raise _ArchiveExportCancelled()
                                if len(raw_line) > MAX_SQL_LINE_BYTES or b"\x00" in raw_line:
                                    raise ValueError(f"archive {quarter} memiliki SQL line tidak valid")
                                line = raw_line.decode("utf-8")
                                stripped = line.strip()
                                if (
                                    not stripped
                                    or stripped.startswith("--")
                                    or stripped.upper() in {"START TRANSACTION;", "COMMIT;"}
                                ):
                                    continue
                                table = _insert_table(stripped)
                                if table not in TABLE_COLUMNS or not _has_one_terminator(stripped):
                                    raise ValueError(f"archive {quarter} memiliki SQL statement tidak diizinkan")
                                sql_counts[table] += 1
                                # Each quarterly dump contains a full device
                                # snapshot. Keep one copy only if later
                                # snapshots are byte-identical.
                                if table == "device":
                                    device_lines.append(stripped)
                                    if quarter_index:
                                        continue
                                if bytes_written + len(raw_line) > MAX_EXPORT_BYTES:
                                    raise ValueError("hasil export archive terlalu besar")
                                output.write(raw_line)
                                encoded = len(raw_line)
                                bytes_written += encoded
                                rows_read += 1
                                if rows_read > MAX_EXPORT_ROWS:
                                    raise ValueError("hasil export archive memiliki terlalu banyak row")
                                if rows_read - last_progress_rows >= 1000 or bytes_written - last_progress_bytes >= 1024 * 1024:
                                    progress(self._update(job_id, partitions_read=partitions_read, rows_read=rows_read, bytes_written=bytes_written))
                                    last_progress_bytes, last_progress_rows = bytes_written, rows_read
                            if sql_counts != expected_counts:
                                raise ValueError(
                                    f"archive {quarter} SQL row count mismatch: expected {expected_counts}, found {sql_counts}"
                                )
                    if quarter_index:
                        if device_lines != baseline_device_lines:
                            raise ValueError(f"archive {quarter} memiliki snapshot device berbeda")
                    else:
                        baseline_device_lines = device_lines
                    partitions_read += 1
                    progress(self._update(job_id, partitions_read=partitions_read, rows_read=rows_read, bytes_written=bytes_written))
                ending = b"COMMIT;\n"
                output.write(ending)
                bytes_written += len(ending)
                output.flush()
            if self._shutdown_event.is_set():
                raise _ArchiveExportCancelled()
            temp.replace(destination)
            self._update(job_id, status="completed", partitions_read=partitions_read, rows_read=rows_read,
                         bytes_written=bytes_written, artifact_name=destination.name, phase="completed")
        except _ArchiveExportCancelled:
            LOG.info("archive export cancelled during shutdown job_id=%s", job_id)
            if temp is not None:
                temp.unlink(missing_ok=True)
            self._update(job_id, status="failed", error="export dibatalkan saat shutdown; gunakan Coba lagi untuk memulai dari awal", phase="failed")
        except Exception as exc:
            LOG.exception("archive export failed job_id=%s", job_id)
            if temp is not None:
                temp.unlink(missing_ok=True)
            reason = str(exc).strip() or "penggabungan archive gagal"
            self._update(job_id, status="failed", error=reason[:1000], phase="failed")
        finally:
            with self._futures_lock:
                self._futures.pop(job_id, None)

    def artifact(self, job_id: str) -> tuple[dict[str, Any], Path]:
        item = self.get(job_id)
        if item is None:
            raise KeyError("archive export tidak ditemukan")
        if item["status"] != "completed" or item["artifact_name"] != f"radmon-archive-{job_id}.sql":
            raise ValueError("archive export belum siap")
        artifact_dir = self._safe_artifact_dir()
        raw_path = artifact_dir / item["artifact_name"]
        if raw_path.is_symlink():
            raise ValueError("file export tidak ditemukan")
        path = raw_path.resolve()
        if path.parent != artifact_dir or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("file export tidak ditemukan")
        return item, path

    def shutdown(self, timeout: float = 15.0) -> None:
        """Cancel queued jobs and boundedly await active atomic exports."""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._shutdown_event.set()
        with self._futures_lock:
            futures = list(self._futures.values())
        for job_id, future in list(self._futures.items()):
            if hasattr(future, "cancel"):
                cancelled = bool(future.cancel())
                if cancelled:
                    self._update(
                        job_id,
                        status="failed",
                        error="export dibatalkan saat shutdown; gunakan Coba lagi untuk memulai dari awal",
                        phase="failed",
                    )
                    with self._futures_lock:
                        self._futures.pop(job_id, None)
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
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
            LOG.warning("archive export workers did not stop within %.1fs", max(0.1, float(timeout)))
