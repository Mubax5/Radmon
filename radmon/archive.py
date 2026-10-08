from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Callable
import zipfile
from zoneinfo import ZoneInfo

from .archive_store import TABLE_COLUMNS
from .quarters import Quarter, quarter_for


REQUIRED_ARCHIVE_FILES = {
    "manifest.json",
    "monthly-recap.csv",
    "device.csv",
    "measurement.csv",
    "alarm.csv",
    "rawdata.csv",
    "applog.csv",
    "news.csv",
}

RECAP_COLUMNS = (
    "year", "month", "serid", "name", "location", "first_measurement",
    "last_measurement", "sample_count", "minimum", "average", "maximum",
    "dose_sum", "rate_sum", "alert_count", "alarm_count",
)


class ArchiveCorruptionError(RuntimeError):
    pass


MAX_ARCHIVE_MEMBERS = 64
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MANIFEST_BYTES = 4 * 1024 * 1024
_QUARTER_ID = re.compile(r"[0-9]{4}-Q[1-4]\Z")


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _csv_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return "" if value is None else value


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip(".")
    else:
        text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quarter_from_id(quarter_id: str, timezone_name: str = "Asia/Jakarta") -> Quarter:
    try:
        year_text, q_text = quarter_id.split("-Q", 1)
        year = int(year_text)
        number = int(q_text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"quarter id tidak valid: {quarter_id}") from exc
    if number not in {1, 2, 3, 4}:
        raise ValueError(f"quarter id tidak valid: {quarter_id}")
    zone = ZoneInfo(timezone_name)
    start_month = (number - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=zone)
    end = datetime(year + 1, 1, 1, tzinfo=zone) if number == 4 else datetime(year, start_month + 3, 1, tzinfo=zone)
    return Quarter(year=year, number=number, start=start, end=end)


def _bounded_zip_infos(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Validate ZIP metadata before any member is decompressed."""
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveCorruptionError("archive memiliki terlalu banyak member")
    result: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        name = str(info.filename)
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or ".." in path.parts
            or name in result
            or info.is_dir()
        ):
            if name in result:
                # Keep the legacy diagnostic wording useful for callers that
                # classify a duplicate payload as an integrity/checksum issue;
                # the duplicate is still rejected before any payload is used.
                raise ArchiveCorruptionError(f"checksum mismatch: duplicate archive member {name}")
            raise ArchiveCorruptionError("nama member archive tidak aman")
        mode = (int(info.external_attr) >> 16) & 0o170000
        if mode == 0o120000:
            raise ArchiveCorruptionError("archive symlink tidak diizinkan")
        size = int(info.file_size)
        if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
            raise ArchiveCorruptionError("member archive terlalu besar")
        total += size
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            raise ArchiveCorruptionError("payload archive terlalu besar")
        if size > 1024 * 1024 and int(info.compress_size) > 0:
            if size / int(info.compress_size) > 1000:
                raise ArchiveCorruptionError("rasio kompresi archive tidak aman")
        result[name] = info
    return result


def _read_bounded_member(archive: zipfile.ZipFile, name: str, maximum: int) -> bytes:
    try:
        with archive.open(name) as handle:
            chunks: list[bytes] = []
            total = 0
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += len(chunk)
                if total > maximum:
                    raise ArchiveCorruptionError(f"member archive terlalu besar: {name}")
                chunks.append(chunk)
            return b"".join(chunks)
    except KeyError as exc:
        raise ArchiveCorruptionError(f"archive member missing: {name}") from exc


def verify_archive(path: Path | str, expected_quarter: Quarter | None = None) -> dict[str, Any]:
    archive_path = Path(path)
    if not archive_path.is_file():
        raise ArchiveCorruptionError(f"archive tidak ditemukan: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = _bounded_zip_infos(archive)
            names = set(infos)
            manifest_bytes = _read_bounded_member(archive, "manifest.json", MAX_ARCHIVE_MANIFEST_BYTES)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict):
                raise ArchiveCorruptionError("manifest archive tidak valid")
            quarter_id = str(manifest["quarter_id"])
            if not _QUARTER_ID.fullmatch(quarter_id):
                raise ArchiveCorruptionError("archive quarter id tidak valid")
            sql_name = f"radmon-{quarter_id}.sql"
            required = set(REQUIRED_ARCHIVE_FILES) | {sql_name}
            missing = sorted(required - names)
            if missing:
                raise ArchiveCorruptionError("archive payload missing: " + ", ".join(missing))
            if expected_quarter is not None and manifest.get("quarter_id") != expected_quarter.quarter_id:
                raise ArchiveCorruptionError("archive quarter mismatch")
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise ArchiveCorruptionError("manifest files tidak valid")
            for name, metadata in files.items():
                if not isinstance(name, str) or name not in names:
                    raise ArchiveCorruptionError(f"manifest file missing: {name}")
                if not isinstance(metadata, dict):
                    raise ArchiveCorruptionError(f"manifest metadata tidak valid: {name}")
                digest = hashlib.sha256()
                with archive.open(name) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != str(metadata.get("sha256") or ""):
                    raise ArchiveCorruptionError(f"checksum mismatch: {name}")
            row_counts = manifest.get("row_counts")
            if not isinstance(row_counts, dict):
                raise ArchiveCorruptionError("manifest row_counts tidak valid")
            for table, expected in row_counts.items():
                if table not in TABLE_COLUMNS or not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
                    raise ArchiveCorruptionError(f"row-count table tidak valid: {table}")
                member = f"{table}.csv"
                if member not in names:
                    raise ArchiveCorruptionError(f"row-count payload missing: {member}")
                count = 0
                with archive.open(member) as raw:
                    with io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                        reader = csv.DictReader(text)
                        for _ in reader:
                            count += 1
                if count != int(expected):
                    raise ArchiveCorruptionError(
                        f"row count mismatch {table}: expected {expected}, found {count}"
                    )
    except ArchiveCorruptionError:
        raise
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError) as exc:
        raise ArchiveCorruptionError(f"archive rusak: {archive_path}") from exc
    result = dict(manifest)
    result["archive_path"] = str(archive_path)
    result["archive_sha256"] = _sha256_file(archive_path)
    return result


class ArchiveCatalog:
    def __init__(self, security_store, archive_dir: Path | str, *, timezone_name: str = "Asia/Jakarta") -> None:
        self.store = security_store
        self.archive_dir = Path(archive_dir)
        self.timezone_name = timezone_name
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def get(self, quarter_id: str) -> dict[str, Any] | None:
        return self.store.get_archive(quarter_id)

    def list_archives(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_archives(limit)

    def safe_archive_path(self, quarter_id: str, recorded_path: str | None = None) -> Path:
        """Resolve only the canonical retained archive for a quarter."""
        if not _QUARTER_ID.fullmatch(str(quarter_id)):
            raise ArchiveCorruptionError("archive quarter id tidak valid")
        canonical = self.archive_dir.resolve() / str(quarter_id)[:4] / f"radmon-{quarter_id}.zip"
        if canonical.is_symlink():
            raise ArchiveCorruptionError("archive symlink tidak diizinkan")
        expected = canonical.resolve()
        try:
            expected.relative_to(self.archive_dir.resolve())
        except ValueError as exc:
            raise ArchiveCorruptionError("archive path berada di luar direktori arsip") from exc
        if recorded_path is not None and Path(str(recorded_path)).resolve() != expected:
            raise ArchiveCorruptionError("archive path tidak sesuai katalog")
        if not expected.is_file() or expected.is_symlink():
            raise FileNotFoundError(f"archive file tidak ditemukan: {quarter_id}")
        return expected

    def recap(self, quarter_id: str) -> list[dict[str, Any]]:
        item = self.get(quarter_id)
        if item is None or not item.get("archive_path"):
            raise FileNotFoundError(f"archive quarter tidak ditemukan: {quarter_id}")
        path = self.safe_archive_path(quarter_id, str(item["archive_path"]))
        verify_archive(path, expected_quarter=_quarter_from_id(quarter_id, self.timezone_name))
        rows: list[dict[str, Any]] = []
        with zipfile.ZipFile(path) as archive:
            with archive.open("monthly-recap.csv") as raw:
                with io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                    for row in csv.DictReader(text):
                        parsed = dict(row)
                        for key in ("year", "month", "serid", "sample_count", "alert_count", "alarm_count"):
                            parsed[key] = int(parsed[key] or 0)
                        for key in ("minimum", "average", "maximum", "dose_sum", "rate_sum"):
                            parsed[key] = float(parsed[key]) if parsed.get(key) not in (None, "") else None
                        rows.append(parsed)
        return rows

    def reconcile(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        for path in sorted(self.archive_dir.glob("*/radmon-????-Q?.zip")):
            quarter_id = path.stem.removeprefix("radmon-")
            seen.add(quarter_id)
            try:
                manifest = verify_archive(path, expected_quarter=_quarter_from_id(quarter_id, self.timezone_name))
            except Exception as exc:
                existing = self.get(quarter_id)
                if existing is not None:
                    self.store.update_archive_state(
                        quarter_id, "DAMAGED", last_error=str(exc), increment_retry=False
                    )
                continue
            existing = self.get(quarter_id)
            state = "COMPLETE" if existing and existing.get("state") == "COMPLETE" else "SEALED"
            self.store.upsert_archive(
                quarter_id=quarter_id,
                start_at=str(manifest["start"]),
                end_at=str(manifest["end"]),
                state=state,
                archive_path=str(path),
                archive_sha256=str(manifest["archive_sha256"]),
                row_counts=dict(manifest.get("row_counts") or {}),
                drain=dict(manifest.get("drain") or {}),
                created_at=str(manifest.get("created_at") or "") or None,
                sealed_at=str(manifest.get("created_at") or "") or None,
                last_error=None,
            )
        for item in self.list_archives(limit=1000):
            quarter_id = str(item["quarter_id"])
            archive_path = item.get("archive_path")
            if archive_path and quarter_id not in seen and not Path(str(archive_path)).is_file():
                self.store.update_archive_state(
                    quarter_id, "DAMAGED", last_error="archive file missing", increment_retry=False
                )
        return self.list_archives(limit=1000)


class QuarterArchiveService:
    def __init__(
        self,
        store,
        catalog: ArchiveCatalog,
        audit,
        archive_dir: Path | str,
        *,
        timezone_name: str = "Asia/Jakarta",
        verifier: Callable[[Path | str, Quarter | None], dict[str, Any]] = verify_archive,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.audit = audit
        self.archive_dir = Path(archive_dir)
        self.timezone_name = timezone_name
        self.verifier = verifier
        self.now = now or (lambda: datetime.now(ZoneInfo(timezone_name)))
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def _audit(self, action: str, quarter: Quarter, *, success: bool = True, reason: str | None = None, after: Any = None) -> None:
        if self.audit is None:
            return
        self.audit.record(
            action,
            None,
            "archive",
            quarter.quarter_id,
            after=after,
            success=success,
            reason=reason,
            source="central",
        )

    def _ensure_space(self, quarter: Quarter) -> None:
        counts = self.store.row_counts(quarter) if hasattr(self.store, "row_counts") else {}
        estimated = 10 * 1024 * 1024 + sum(int(value) for value in counts.values()) * 512
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.archive_dir).free
        if free < estimated:
            raise RuntimeError(
                f"disk archive tidak cukup: free={free} estimated_required={estimated}"
            )

    def export_quarter(self, quarter: Quarter, drain_info: dict[str, Any]) -> Path:
        year_dir = self.archive_dir / str(quarter.year)
        year_dir.mkdir(parents=True, exist_ok=True)
        final_path = year_dir / f"radmon-{quarter.quarter_id}.zip"
        if final_path.exists():
            self.verifier(final_path, quarter)
            return final_path
        self._ensure_space(quarter)
        with tempfile.TemporaryDirectory(prefix=f"{quarter.quarter_id}-", dir=year_dir) as temp_name:
            temp_dir = Path(temp_name)
            sql_name = f"radmon-{quarter.quarter_id}.sql"
            sql_path = temp_dir / sql_name
            row_counts: dict[str, int] = {}
            stations: list[dict[str, Any]] = []
            with sql_path.open("w", encoding="utf-8", newline="\n") as sql:
                sql.write("-- RadMon quarterly central archive\nSTART TRANSACTION;\n")
                for table, columns in TABLE_COLUMNS.items():
                    csv_path = temp_dir / f"{table}.csv"
                    count = 0
                    with csv_path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                        writer.writeheader()
                        for row in self.store.table_rows(table, quarter):
                            item = {column: _csv_value(row.get(column)) for column in columns}
                            writer.writerow(item)
                            count += 1
                            values = ", ".join(_sql_literal(row.get(column)) for column in columns)
                            sql.write(
                                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values});\n"
                            )
                            if table == "device":
                                stations.append({
                                    "serid": int(row["serid"]),
                                    "name": str(row.get("name") or ""),
                                    "location": str(row.get("location") or ""),
                                })
                    row_counts[table] = count
                sql.write("COMMIT;\n")

            recap_path = temp_dir / "monthly-recap.csv"
            with recap_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=RECAP_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                for row in self.store.monthly_recap_rows(quarter):
                    writer.writerow({column: _csv_value(row.get(column)) for column in RECAP_COLUMNS})

            payload_paths = [
                temp_dir / "device.csv", temp_dir / "measurement.csv", temp_dir / "alarm.csv",
                temp_dir / "rawdata.csv", temp_dir / "applog.csv", temp_dir / "news.csv",
                recap_path, sql_path,
            ]
            file_meta = {
                path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
                for path in payload_paths
            }
            created_at = self.now().isoformat()
            drain = _serialize(drain_info)
            manifest = {
                "format_version": 1,
                "quarter_id": quarter.quarter_id,
                "start": quarter.start.isoformat(),
                "end": quarter.end.isoformat(),
                "created_at": created_at,
                "state": "SEALED",
                "row_counts": row_counts,
                "files": file_meta,
                "drain": drain,
                "sources": sorted({str(key).split(":", 1)[0] for key in drain}),
                "stations": sorted(stations, key=lambda item: int(item["serid"])),
            }
            manifest_path = temp_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp_zip = year_dir / f".{final_path.name}.tmp"
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in [manifest_path, *payload_paths]:
                    info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, path.read_bytes())
            temp_zip.replace(final_path)
        return final_path

    def run_rollover(
        self,
        quarter: Quarter,
        *,
        drain_info: dict[str, Any],
        active_quarter: Quarter | None = None,
    ) -> dict[str, Any]:
        existing = self.catalog.get(quarter.quarter_id)
        if existing is not None and existing.get("state") == "COMPLETE":
            return existing
        if existing is None:
            existing = self.catalog.store.upsert_archive(
                quarter_id=quarter.quarter_id,
                start_at=quarter.start.isoformat(),
                end_at=quarter.end.isoformat(),
                state="OPEN",
                drain=_serialize(drain_info),
                last_error=None,
            )

        path: Path | None = None
        sealed = existing.get("state") in {"SEALED", "PURGING"}
        if sealed and existing.get("archive_path"):
            path = Path(str(existing["archive_path"]))
            try:
                self.verifier(path, quarter)
            except Exception:
                sealed = False

        if not sealed:
            self.catalog.store.update_archive_state(
                quarter.quarter_id,
                "EXPORTING",
                drain=_serialize(drain_info),
                last_error=None,
            )
            self._audit("ARCHIVE_EXPORT_START", quarter, after={"drain": _serialize(drain_info)})
            try:
                path = self.export_quarter(quarter, drain_info)
                self._audit("ARCHIVE_EXPORT_SUCCESS", quarter, after={"archive_path": str(path)})
                self.catalog.store.update_archive_state(
                    quarter.quarter_id,
                    "VERIFYING",
                    archive_path=str(path),
                    last_error=None,
                )
                verified = self.verifier(path, quarter)
            except Exception as exc:
                current = self.catalog.get(quarter.quarter_id)
                failure_state = str(current.get("state") if current else "EXPORTING")
                self.catalog.store.update_archive_state(
                    quarter.quarter_id,
                    failure_state,
                    last_error=str(exc),
                    increment_retry=True,
                )
                action = "ARCHIVE_VERIFY_FAILED" if failure_state == "VERIFYING" else "ARCHIVE_EXPORT_FAILED"
                self._audit(action, quarter, success=False, reason=str(exc))
                raise
            self.catalog.store.update_archive_state(
                quarter.quarter_id,
                "SEALED",
                archive_path=str(path),
                archive_sha256=str(verified["archive_sha256"]),
                row_counts=dict(verified.get("row_counts") or {}),
                drain=dict(verified.get("drain") or {}),
                created_at=str(verified.get("created_at") or "") or None,
                sealed_at=self.now().isoformat(),
                last_error=None,
            )
            self._audit("ARCHIVE_VERIFY_SUCCESS", quarter, after={"archive_sha256": verified["archive_sha256"]})

        self.catalog.store.update_archive_state(
            quarter.quarter_id, "PURGING", last_error=None
        )
        self._audit("ARCHIVE_PURGE_START", quarter)
        try:
            deleted = self.store.purge_quarter(quarter)
            active = active_quarter or quarter_for(self.now(), self.timezone_name)
            self.store.rebuild_recent(active)
        except Exception as exc:
            self.catalog.store.update_archive_state(
                quarter.quarter_id,
                "SEALED",
                last_error=str(exc),
                increment_retry=True,
            )
            self._audit("ARCHIVE_PURGE_FAILED", quarter, success=False, reason=str(exc))
            raise
        now = self.now().isoformat()
        self._audit("ARCHIVE_PURGE_SUCCESS", quarter, after={"deleted": deleted})
        completed = self.catalog.store.update_archive_state(
            quarter.quarter_id,
            "COMPLETE",
            purged_at=now,
            completed_at=now,
            last_error=None,
        )
        self._audit("ARCHIVE_COMPLETE", quarter, after=completed)
        return completed

    def retry(self, quarter_id: str) -> dict[str, Any]:
        item = self.catalog.get(quarter_id)
        if item is None:
            raise KeyError(f"archive quarter tidak ditemukan: {quarter_id}")
        quarter = _quarter_from_id(quarter_id, self.timezone_name)
        return self.run_rollover(
            quarter,
            drain_info=dict(item.get("drain") or {}),
            active_quarter=quarter_for(self.now(), self.timezone_name),
        )
