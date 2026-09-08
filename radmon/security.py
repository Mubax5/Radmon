from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
from typing import Callable


class SecurityError(RuntimeError):
    pass


class Role(str, Enum):
    ADMINISTRATOR = "Administrator"
    OPERATOR = "Operator"
    VIEWER = "Viewer"


@dataclass(frozen=True, slots=True)
class UserIdentity:
    username: str
    display_name: str
    role: Role


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMINISTRATOR: frozenset({
        "view", "ack_alarm", "manage_users", "edit_station", "manage_sources",
    }),
    Role.OPERATOR: frozenset({"view", "ack_alarm"}),
    Role.VIEWER: frozenset({"view"}),
}


class SecurityStore:
    PBKDF2_ITERATIONS = 260_000

    def __init__(
        self,
        path: Path | str,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._init_schema()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  pin_hash TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
CREATE TABLE IF NOT EXISTS audit_events (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at TEXT NOT NULL,
  username TEXT,
  role TEXT,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  source TEXT,
  before_json TEXT,
  after_json TEXT,
  success INTEGER NOT NULL,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS remote_alarm_state (
  source_id TEXT NOT NULL,
  serid INTEGER NOT NULL,
  remote_serid INTEGER,
  event_time TEXT NOT NULL,
  level TEXT NOT NULL,
  measured_value REAL,
  threshold REAL,
  hit_count INTEGER,
  acknowledged_at TEXT,
  pic TEXT,
  action TEXT,
  note TEXT,
  notification_sent_at TEXT,
  PRIMARY KEY (source_id, serid, event_time)
);
CREATE TABLE IF NOT EXISTS lan_checkpoints (
  source_id TEXT NOT NULL,
  serid INTEGER NOT NULL,
  last_dtom TEXT NOT NULL,
  PRIMARY KEY (source_id, serid)
);
CREATE TABLE IF NOT EXISTS source_station_map (
  source_id TEXT NOT NULL,
  remote_serid INTEGER NOT NULL,
  central_serid INTEGER NOT NULL,
  PRIMARY KEY (source_id, remote_serid)
);
"""
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(remote_alarm_state)").fetchall()
            }
            if "remote_serid" not in columns:
                connection.execute("ALTER TABLE remote_alarm_state ADD COLUMN remote_serid INTEGER")
            connection.execute(
                "UPDATE remote_alarm_state SET remote_serid = serid WHERE remote_serid IS NULL"
            )

    @classmethod
    def _hash_secret(cls, value: str) -> str:
        if not value:
            raise ValueError("secret must not be empty")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", value.encode("utf-8"), salt, cls.PBKDF2_ITERATIONS
        )
        return f"pbkdf2_sha256${cls.PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_secret(value: str, encoded: str) -> bool:
        try:
            algorithm, iterations_text, salt_hex, digest_hex = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                value.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations_text),
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    def create_user(
        self,
        username: str,
        display_name: str,
        role: Role | str,
        password: str,
        pin: str,
        *,
        actor: str | None = None,
    ) -> UserIdentity:
        name = username.strip().lower()
        if not name or len(name) > 64:
            raise ValueError("username tidak valid")
        if len(password) < 8:
            raise ValueError("password minimal 8 karakter")
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise ValueError("PIN harus 4-8 digit")
        selected_role = role if isinstance(role, Role) else Role(role)
        now = self._now().isoformat()
        with self._connection() as connection:
            connection.execute(
                """
INSERT INTO users
  (username, display_name, role, password_hash, pin_hash, enabled, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, 1, ?, ?)
""",
                (
                    name,
                    display_name.strip() or name,
                    selected_role.value,
                    self._hash_secret(password),
                    self._hash_secret(pin),
                    now,
                    now,
                ),
            )
        return UserIdentity(name, display_name.strip() or name, selected_role)

    def bootstrap_admin(self, username: str, password: str, pin: str) -> UserIdentity | None:
        with self._connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if count:
            return None
        return self.create_user(username, username, Role.ADMINISTRATOR, password, pin)

    def authenticate(self, username: str, password: str) -> UserIdentity | None:
        name = username.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT display_name, role, password_hash, enabled FROM users WHERE username = ?",
                (name,),
            ).fetchone()
        if not row or not int(row[3]) or not self._verify_secret(password, row[2]):
            return None
        return UserIdentity(name, str(row[0]), Role(str(row[1])))

    def verify_pin(self, username: str, pin: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT pin_hash, enabled FROM users WHERE username = ?",
                (username.strip().lower(),),
            ).fetchone()
        return bool(row and int(row[1]) and self._verify_secret(pin, str(row[0])))

    def set_user_enabled(self, username: str, enabled: bool) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE users SET enabled = ?, updated_at = ? WHERE username = ?",
                (1 if enabled else 0, self._now().isoformat(), username.strip().lower()),
            )

    def reset_password(self, username: str, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password minimal 8 karakter")
        with self._connection() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
                (self._hash_secret(password), self._now().isoformat(), username.strip().lower()),
            )

    def reset_pin(self, username: str, pin: str) -> None:
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise ValueError("PIN harus 4-8 digit")
        with self._connection() as connection:
            connection.execute(
                "UPDATE users SET pin_hash = ?, updated_at = ? WHERE username = ?",
                (self._hash_secret(pin), self._now().isoformat(), username.strip().lower()),
            )

    def list_users(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT username, display_name, role, enabled, created_at, updated_at FROM users ORDER BY username"
            ).fetchall()
        return [
            {
                "username": row[0],
                "display_name": row[1],
                "role": row[2],
                "enabled": bool(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    @staticmethod
    def role_allows(role: Role | str, permission: str) -> bool:
        selected = role if isinstance(role, Role) else Role(role)
        return permission in ROLE_PERMISSIONS[selected]

    def require_sensitive(self, identity: UserIdentity | None, permission: str, pin: str) -> None:
        if identity is None or not self.role_allows(identity.role, permission):
            raise SecurityError("aksi tidak diizinkan")
        if not self.verify_pin(identity.username, pin):
            raise SecurityError("PIN tidak valid")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(self, username: str, ttl_seconds: int = 28_800) -> str:
        name = username.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT enabled FROM users WHERE username = ?", (name,)
            ).fetchone()
            if not row or not int(row[0]):
                raise SecurityError("user tidak aktif")
            token = secrets.token_urlsafe(32)
            now = self._now()
            expires = now + timedelta(seconds=max(60, int(ttl_seconds)))
            connection.execute(
                "INSERT INTO sessions (token_hash, username, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (self._token_hash(token), name, expires.isoformat(), now.isoformat()),
            )
        return token

    def session_user(self, token: str | None) -> UserIdentity | None:
        if not token:
            return None
        now = self._now()
        with self._connection() as connection:
            row = connection.execute(
                """
SELECT u.username, u.display_name, u.role, u.enabled, s.expires_at
FROM sessions s JOIN users u ON u.username = s.username
WHERE s.token_hash = ?
""",
                (self._token_hash(token),),
            ).fetchone()
            if not row:
                return None
            expires = datetime.fromisoformat(str(row[4]))
            if not int(row[3]) or expires <= now:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),)
                )
                return None
        return UserIdentity(str(row[0]), str(row[1]), Role(str(row[2])))

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),)
            )

    def resolve_station(self, source_id: str, remote_serid: int) -> int:
        """Return stable central identity for a production station.

        The first observation maps remote SERID to itself.  A later central Tag
        migration changes only ``central_serid`` so LAN checkpoints and ACK still
        address the original production identifier.
        """
        source = source_id.strip()
        remote = int(remote_serid)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT central_serid FROM source_station_map WHERE source_id = ? AND remote_serid = ?",
                (source, remote),
            ).fetchone()
            if row is not None:
                return int(row[0])
            connection.execute(
                "INSERT INTO source_station_map (source_id, remote_serid, central_serid) VALUES (?, ?, ?)",
                (source, remote, remote),
            )
        return remote

    def remap_central_serid(self, old_serid: int, new_serid: int) -> None:
        old = int(old_serid)
        new = int(new_serid)
        with self._connection() as connection:
            connection.execute(
                "UPDATE source_station_map SET central_serid = ? WHERE central_serid = ?",
                (new, old),
            )
            connection.execute(
                "UPDATE remote_alarm_state SET serid = ? WHERE serid = ?",
                (new, old),
            )
