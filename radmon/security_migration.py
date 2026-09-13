from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3
from typing import Iterable

from .security import Role, SecurityStore


_LOG = logging.getLogger(__name__)
_REQUIRED_USER_COLUMNS = {
    "username",
    "display_name",
    "role",
    "password_hash",
    "pin_hash",
    "enabled",
    "created_at",
    "updated_at",
}


def _valid_secret_hash(value: object) -> bool:
    text = str(value or "")
    parts = text.split("$", 3)
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        return int(parts[1]) > 0 and bool(bytes.fromhex(parts[2])) and bool(bytes.fromhex(parts[3]))
    except (TypeError, ValueError):
        return False


def import_users_from_database(store: SecurityStore, legacy_path: Path | str) -> int:
    """Copy compatible legacy RadMon users into an empty production store.

    Password and PIN hashes are preserved byte-for-byte, so the credentials created
    by the Python-era application continue to work. Sessions and other runtime state
    are intentionally not imported.
    """
    if store.list_users():
        return 0

    source = Path(legacy_path).expanduser()
    try:
        source = source.resolve()
        target = store.path.resolve()
    except OSError:
        return 0
    if source == target or not source.is_file():
        return 0

    try:
        connection = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if not _REQUIRED_USER_COLUMNS.issubset(columns):
                return 0
            rows = connection.execute(
                """
SELECT username, display_name, role, password_hash, pin_hash,
       enabled, created_at, updated_at
FROM users
ORDER BY username
"""
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        _LOG.warning("Legacy RadMon security database could not be read from %s: %s", source, exc)
        return 0

    if not rows:
        return 0

    validated: list[tuple[object, ...]] = []
    try:
        for row in rows:
            username = str(row[0] or "").strip().lower()
            display_name = str(row[1] or "").strip() or username
            role = Role(str(row[2])).value
            password_hash = str(row[3] or "")
            pin_hash = str(row[4] or "")
            if not username or len(username) > 64:
                return 0
            if not _valid_secret_hash(password_hash) or not _valid_secret_hash(pin_hash):
                return 0
            validated.append(
                (
                    username,
                    display_name,
                    role,
                    password_hash,
                    pin_hash,
                    1 if bool(row[5]) else 0,
                    str(row[6] or ""),
                    str(row[7] or ""),
                )
            )
    except (TypeError, ValueError):
        return 0

    try:
        with store._connection() as target_connection:
            existing = int(target_connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            if existing:
                return 0
            target_connection.executemany(
                """
INSERT INTO users
  (username, display_name, role, password_hash, pin_hash, enabled, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""",
                validated,
            )
    except sqlite3.Error as exc:
        _LOG.warning("Legacy RadMon users could not be imported from %s: %s", source, exc)
        return 0

    return len(validated)


def _append_candidate(items: list[Path], candidate: Path | str | None, target: Path) -> None:
    if not candidate:
        return
    path = Path(candidate).expanduser()
    try:
        resolved = path.resolve()
        if resolved == target.resolve() or not resolved.is_file():
            return
    except OSError:
        return
    if resolved not in items:
        items.append(resolved)


def _profile_candidates(profile: Path) -> Iterable[Path]:
    bases = [
        profile,
        profile / "Desktop",
        profile / "Documents",
        profile / "Downloads",
        profile / "Projects",
        profile / "repos",
        profile / "source",
        profile / "Documents" / "GitHub",
    ]
    names = ("Radmon", "RadMon", "radmon")
    for base in bases:
        yield base / "runtime" / "radmon-security.db"
        for name in names:
            yield base / name / "runtime" / "radmon-security.db"
        try:
            yield from base.glob("*/runtime/radmon-security.db")
        except OSError:
            continue


def legacy_security_candidates(target_path: Path | str) -> list[Path]:
    """Return plausible Python-era security databases, explicit override first."""
    target = Path(target_path)
    explicit: list[Path] = []
    discovered: list[Path] = []

    _append_candidate(explicit, os.getenv("RADMON_LEGACY_SECURITY_DB", "").strip(), target)

    cwd = Path.cwd()
    _append_candidate(discovered, cwd / "runtime" / "radmon-security.db", target)
    package_root = Path(__file__).resolve().parents[1]
    _append_candidate(discovered, package_root / "runtime" / "radmon-security.db", target)

    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:")
        users_root = Path(system_drive + "\\") / "Users"
        try:
            profiles = [p for p in users_root.iterdir() if p.is_dir()]
        except OSError:
            profiles = []
        ignored = {"all users", "default", "default user", "public"}
        for profile in profiles:
            if profile.name.lower() in ignored:
                continue
            for candidate in _profile_candidates(profile):
                _append_candidate(discovered, candidate, target)

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    discovered.sort(key=mtime, reverse=True)
    return explicit + [path for path in discovered if path not in explicit]


def migrate_legacy_users(store: SecurityStore) -> Path | None:
    """Import the newest compatible legacy user store only when production is empty."""
    if store.list_users():
        return None
    for candidate in legacy_security_candidates(store.path):
        imported = import_users_from_database(store, candidate)
        if imported:
            _LOG.info("Imported %d legacy RadMon user(s) from %s", imported, candidate)
            return candidate
    return None
