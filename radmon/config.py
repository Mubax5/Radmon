from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import secrets
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


GRAFANA_PASSWORD_PLACEHOLDER = "GENERATE_ON_FIRST_START"
_GRAFANA_WEAK_PASSWORDS = frozenset({
    "admin", "password", "changeme", "change_me", "generate_on_first_start",
})


def is_safe_grafana_password(value: str | None) -> bool:
    """Check a managed Grafana secret without exposing its value."""
    password = str(value or "")
    return len(password) >= 20 and password.casefold() not in _GRAFANA_WEAK_PASSWORDS


def ensure_grafana_password(env_file: str | Path) -> bool:
    """Atomically generate only the explicit first-install password marker.

    Legacy values such as ``admin`` are deliberately not replaced: an upgrade
    must not silently rotate a credential that operators may already know.
    """
    path = Path(env_file)
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    key_index = None
    current = None
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*RADMON_GRAFANA_PASSWORD\s*=)(.*?)(\r?\n)?$", line)
        if match:
            key_index = index
            current = match.group(2).strip().strip("\"'")
    if key_index is None or current != GRAFANA_PASSWORD_PLACEHOLDER:
        return False

    generated = secrets.token_urlsafe(32)
    line = lines[key_index]
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    lines[key_index] = line.split("=", 1)[0] + "=" + generated + newline

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write("".join(lines))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return True


@dataclass(frozen=True, slots=True)
class Settings:
    serial_port: str = "COM15"
    detectors: str = ""
    baudrate: int = 2400
    serial_timeout: float = 3.0
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "ipradmon"
    serid: int = 5201
    building: str = "52"
    room: str = "IS-1"
    location: str = "Gd.52"
    warnlevel: float = 23.0
    alarmlevel: float = 25.0
    maxidlemin: int = 30
    unit: str = "µSv/h"
    sample_interval: float = 2.0
    refresh_interval: float = 2.0
    dummy_mode: str = "normal"
    sync_enabled: bool = False
    central_url: str = ""
    central_token: str = ""
    sync_batch_size: int = 100
    sync_timeout: float = 10.0
    sync_initial_lookback_hours: int = 24
    grafana_url: str = "http://localhost:3000/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv"
    grafana_fallback_port: int = 3300
    grafana_user: str = "admin"
    grafana_password: str = ""
    grafana_bin: str = ""
    web_cookie_secure: bool = True
    report_dir: Path = Path("!REPORT!")
    security_db: Path | None = None
    application_dir: Path | None = None
    runtime_dir: Path = Path("runtime")
    log_dir: Path = Path("logs")
    single_instance_port: int = 47652
    central_host: str = "192.168.1.2"
    lan_enabled: bool = False
    archive_enabled: bool = True
    archive_dir: Path = Path("archives")
    archive_timezone: str = "Asia/Jakarta"
    archive_min_retention_years: int = 5
    archive_check_interval: float = 60.0
    # Empty by default: forwarded client identity is never trusted unless an
    # operator explicitly names the reverse-proxy networks.
    trusted_proxy_nets: tuple[str, ...] = ()
    web_allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "Settings":
        if load_dotenv is not None and env_file:
            load_dotenv(str(env_file), override=False)
        get = os.getenv
        dummy_mode = get("RADMON_DUMMY_MODE", "normal").strip().lower()
        if dummy_mode not in {"normal", "alert", "alarm", "mixed"}:
            raise ValueError("RADMON_DUMMY_MODE harus normal, alert, alarm, atau mixed")
        archive_retention = int(get("RADMON_ARCHIVE_MIN_RETENTION_YEARS", "5"))
        if archive_retention < 5:
            raise ValueError("RADMON_ARCHIVE_MIN_RETENTION_YEARS minimal 5 tahun")
        archive_timezone = get("RADMON_ARCHIVE_TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta"
        try:
            ZoneInfo(archive_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"timezone archive tidak valid: {archive_timezone}") from exc
        archive_check_interval = float(get("RADMON_ARCHIVE_CHECK_INTERVAL", "60"))
        if archive_check_interval <= 0:
            raise ValueError("RADMON_ARCHIVE_CHECK_INTERVAL harus lebih dari 0")
        trusted_proxy_nets = tuple(
            item.strip() for item in get("RADMON_TRUSTED_PROXY_NETS", "").split(",") if item.strip()
        )
        web_allowed_origins = tuple(
            item.strip() for item in get("RADMON_WEB_ALLOWED_ORIGINS", "").split(",") if item.strip()
        )
        return cls(
            serial_port=get("RADMON_SERIAL_PORT", "COM15"),
            detectors=get("RADMON_DETECTORS", ""),
            baudrate=int(get("RADMON_BAUDRATE", "2400")),
            serial_timeout=float(get("RADMON_SERIAL_TIMEOUT", "3")),
            db_host=get("RADMON_DB_HOST", "localhost"),
            db_port=int(get("RADMON_DB_PORT", "3306")),
            db_user=get("RADMON_DB_USER", "root"),
            db_password=get("RADMON_DB_PASSWORD", ""),
            db_name=get("RADMON_DB_NAME", "ipradmon"),
            serid=int(get("RADMON_SERID", "5201")),
            building=get("RADMON_BUILDING", "52"),
            room=get("RADMON_ROOM", "IS-1"),
            location=get("RADMON_LOCATION", "Gd.52"),
            warnlevel=float(get("RADMON_WARNLEVEL", "23")),
            alarmlevel=float(get("RADMON_ALARMLEVEL", "25")),
            maxidlemin=int(get("RADMON_MAXIDLEMIN", "30")),
            unit=get("RADMON_UNIT", "µSv/h").replace("μ", "µ").replace("uSv/h", "µSv/h"),
            sample_interval=float(get("RADMON_SAMPLE_INTERVAL", "2")),
            refresh_interval=float(get("RADMON_REFRESH_INTERVAL", "2")),
            dummy_mode=dummy_mode,
            sync_enabled=_as_bool(get("RADMON_SYNC_ENABLED"), False),
            central_url=get("RADMON_CENTRAL_URL", ""),
            central_token=get("RADMON_CENTRAL_TOKEN", ""),
            sync_batch_size=int(get("RADMON_SYNC_BATCH_SIZE", "100")),
            sync_timeout=float(get("RADMON_SYNC_TIMEOUT", "10")),
            sync_initial_lookback_hours=int(get("RADMON_SYNC_INITIAL_LOOKBACK_HOURS", "24")),
            grafana_url=get(
                "RADMON_GRAFANA_URL",
                "http://localhost:3000/d/radmon-radiation-monitoring/radiation-monitoring?orgId=1&refresh=2s&kiosk=tv",
            ),
            grafana_fallback_port=int(get("RADMON_GRAFANA_PORT", "3300")),
            grafana_user=get("RADMON_GRAFANA_USER", "admin"),
            grafana_password=get("RADMON_GRAFANA_PASSWORD", ""),
            grafana_bin=get("RADMON_GRAFANA_BIN", "").strip(),
            web_cookie_secure=_as_bool(get("RADMON_WEB_COOKIE_SECURE"), True),
            report_dir=Path(get("RADMON_REPORT_DIR", "!REPORT!")),
            security_db=Path(get("RADMON_SECURITY_DB", "runtime/radmon-security.db")),
            runtime_dir=Path(get("RADMON_RUNTIME_DIR", "runtime")),
            log_dir=Path(get("RADMON_LOG_DIR", "logs")),
            single_instance_port=int(get("RADMON_SINGLE_INSTANCE_PORT", "47652")),
            central_host=get("RADMON_CENTRAL_HOST", "192.168.1.2"),
            lan_enabled=_as_bool(get("RADMON_LAN_ENABLED"), False),
            archive_enabled=_as_bool(get("RADMON_ARCHIVE_ENABLED"), True),
            archive_dir=Path(get("RADMON_ARCHIVE_DIR", "archives")),
            archive_timezone=archive_timezone,
            archive_min_retention_years=archive_retention,
            archive_check_interval=archive_check_interval,
            trusted_proxy_nets=trusted_proxy_nets,
            web_allowed_origins=web_allowed_origins,
        )

    def for_application_paths(self, paths: "ApplicationPaths") -> "Settings":
        def resolved(value: Path, default: Path) -> Path:
            if value.is_absolute():
                return value
            default_names = {"runtime", "archives", "logs", "!REPORT!", "reports"}
            return default if str(value) in default_names else paths.install_root / value

        return replace(
            self,
            runtime_dir=resolved(self.runtime_dir, paths.runtime_dir),
            archive_dir=resolved(self.archive_dir, paths.archive_dir),
            report_dir=resolved(self.report_dir, paths.report_dir),
            log_dir=resolved(self.log_dir, paths.log_dir),
            security_db=(
                (self.security_db if self.security_db.is_absolute() else paths.install_root / self.security_db).resolve()
                if self.security_db is not None else (paths.runtime_dir / "radmon-security.db").resolve()
            ),
            application_dir=paths.app_dir.resolve(),
        )

    def detector_bindings(self) -> list[tuple[int, str]]:
        raw = self.detectors.strip()
        if not raw:
            return [(self.serid, self.serial_port.strip())]

        bindings: list[tuple[int, str]] = []
        seen: set[int] = set()
        for entry in raw.split(";"):
            item = entry.strip()
            if not item or item.count("@") != 1:
                raise ValueError("RADMON_DETECTORS harus berbentuk SERID@PORT;SERID@PORT")
            serid_text, port = (part.strip() for part in item.split("@", 1))
            if not serid_text.isdigit() or int(serid_text) <= 0 or not port:
                raise ValueError(f"Binding detector tidak valid: {item!r}")
            serid = int(serid_text)
            if serid in seen:
                raise ValueError(f"SERID detector duplikat: {serid}")
            seen.add(serid)
            bindings.append((serid, port))
        return bindings

    def for_dummy(self) -> "Settings":
        return replace(
            self,
            serid=5202,
            building="52",
            room="IS-1 Koridor",
            location="Gd.52",
            warnlevel=8.0,
            alarmlevel=10.0,
            maxidlemin=30,
            unit="µSv/h",
            sample_interval=2.0,
            refresh_interval=2.0,
        )

    @property
    def station_label(self) -> str:
        return f"[{self.serid}] {self.room} ({self.location})"
