from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from typing import Callable, Any


@dataclass(frozen=True, slots=True)
class PortOwner:
    pid: int
    command_line: str


def _runner_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "check": False,
        "timeout": 5,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _run_powershell(command: str, *, runner: Callable[..., Any]) -> Any:
    return runner(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        **_runner_kwargs(),
    )


def find_listener_owner(
    port: int,
    runner: Callable[..., Any] = subprocess.run,
) -> PortOwner | None:
    """Return the Windows process that owns a listening TCP port, if resolvable.

    Failure to inspect is treated conservatively as no positively identified owner;
    callers still rely on actual server bind failure rather than killing anything.
    """
    port = int(port)
    try:
        result = _run_powershell(
            "(Get-NetTCPConnection "
            f"-LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess)",
            runner=runner,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None

    pid_text = next(
        (line.strip() for line in (getattr(result, "stdout", "") or "").splitlines() if line.strip().isdigit()),
        "",
    )
    if not pid_text:
        return None
    pid = int(pid_text)

    try:
        command = _run_powershell(
            "(Get-CimInstance Win32_Process "
            f"-Filter \"ProcessId = {pid}\" -ErrorAction SilentlyContinue).CommandLine",
            runner=runner,
        )
    except (OSError, subprocess.SubprocessError):
        return PortOwner(pid, "")
    command_line = ""
    if getattr(command, "returncode", 1) == 0:
        command_line = (getattr(command, "stdout", "") or "").strip()
    return PortOwner(pid, command_line)


def is_legacy_radmon_central(owner: PortOwner, port: int) -> bool:
    """Recognize only the old RadMon central_server.py listener.

    If the legacy command specifies --port, it must equal ``port``. When no
    explicit port is present, the caller's listener lookup already proves the
    process owns ``port`` and central_server.py's legacy default is 8090.
    """
    command = owner.command_line.strip()
    if not command:
        return False
    normalized = command.replace("/", "\\")
    if not re.search(r"\\radmon\\central_server\.py(?:\s|\"|'|$)", normalized, re.IGNORECASE):
        return False

    port_matches = re.findall(r"(?:^|\s)--port(?:\s+|=)(\d+)(?=\s|$)", command, re.IGNORECASE)
    if port_matches:
        return all(int(value) == int(port) for value in port_matches)
    return int(port) == 8090


def stop_legacy_radmon_central(
    owner: PortOwner,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    if not is_legacy_radmon_central(owner, 8090):
        raise RuntimeError(f"PID {owner.pid} bukan legacy RadMon central")
    try:
        result = _run_powershell(
            f"Stop-Process -Id {int(owner.pid)} -Force -ErrorAction Stop",
            runner=runner,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"gagal menghentikan legacy RadMon PID {owner.pid}") from exc
    if getattr(result, "returncode", 1) != 0:
        detail = (getattr(result, "stderr", "") or "").strip()
        raise RuntimeError(
            f"gagal menghentikan legacy RadMon PID {owner.pid}"
            + (f": {detail}" if detail else "")
        )
