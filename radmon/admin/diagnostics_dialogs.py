from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


def _health_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if not value:
        return "http://127.0.0.1:8090/health"
    if value.endswith("/health"):
        return value
    return value + "/health"


def server_health_lines(
    url: str,
    timeout: float = 3.0,
    *,
    opener: Callable[..., Any] | None = None,
) -> list[str]:
    """Run a read-only HTTP GET health probe and return legacy-style log lines."""
    target = _health_url(url)
    lines = [
        f"[Server] {target}",
        "[method] GET",
        "[description] RadMon central health/readiness test",
    ]
    request = Request(target, method="GET", headers={"Accept": "application/json"})
    open_fn = opener or urlopen
    try:
        response = open_fn(request, timeout=float(timeout))
        try:
            status = getattr(response, "status", None)
            payload = response.read(4096)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        text = payload.decode("utf-8", errors="replace").strip()
        lines.append(f"[status] HTTP {status if status is not None else 'OK'}")
        if text:
            try:
                compact = json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True)
            except (json.JSONDecodeError, TypeError, ValueError):
                compact = text
            lines.append(f"[Response] {compact[:1000]}")
        else:
            lines.append("[Response] empty body")
    except Exception as exc:
        lines.append(f"[Error] {type(exc).__name__}: {exc}")
    lines.append("[Server Tester] Finished")
    return lines


def hardware_test_lines(
    bindings: Iterable[tuple[int, str]],
    baudrate: int,
    timeout: float,
    *,
    serial_factory: Callable[..., Any] | None = None,
) -> list[str]:
    """Open/read/close configured serial ports without sending detector commands."""
    if serial_factory is None:
        import serial

        serial_factory = serial.Serial

    lines: list[str] = []
    items = list(bindings)
    if not items:
        return ["[System] No local detector binding configured.", "[Hardware Tester] Finished"]

    for serid, port in items:
        serial_port = None
        lines.append(f"[{port}] Opening serial port for SERID {serid}.")
        try:
            serial_port = serial_factory(
                port=port,
                baudrate=int(baudrate),
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=max(0.01, min(float(timeout), 1.0)),
            )
            lines.append(f"[{port}] Port opened; trying read-only sample.")
            raw = serial_port.readline()
            if raw:
                if isinstance(raw, bytes):
                    text = raw.decode("ascii", errors="replace").strip()
                else:
                    text = str(raw).strip()
                lines.append(f"[{port}] Read sample: {text[:160]}")
            else:
                lines.append(f"[{port}] Read timed out (no data).")
        except Exception as exc:
            lines.append(f"[System] {port}: {type(exc).__name__}: {exc}")
        finally:
            if serial_port is not None:
                close = getattr(serial_port, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception as exc:
                        lines.append(f"[System] {port}: close error: {exc}")
            lines.append(f"[Hardware Tester] {port} test finished")
    return lines


class _LogDialog(QDialog):
    def __init__(self, title: str, lines: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 380)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlainText("\n".join(lines))
        self.save_button = QPushButton("Save...")
        self.close_button = QPushButton("Close")
        self.save_button.clicked.connect(self.save_log)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.output, 1)
        layout.addLayout(buttons)

    def save_log(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Save diagnostics", "radmon-diagnostics.txt", "Text (*.txt)")
        if filename:
            Path(filename).write_text(self.output.toPlainText(), encoding="utf-8")


class ServerTestDialog(_LogDialog):
    def __init__(self, server_uri: str, parent=None) -> None:
        super().__init__("Server test", server_health_lines(server_uri), parent)


class HardwareTestDialog(_LogDialog):
    def __init__(self, settings, *, source: str, parent=None) -> None:
        if source == "lan":
            lines = [
                "[System] LAN mode: detector hardware belongs to production sources.",
                "[System] Desktop will not open or control production serial hardware.",
                "[System] LAN collection is owned by central_server.py.",
                "[Hardware Tester] Finished",
            ]
        else:
            try:
                bindings = settings.detector_bindings()
            except Exception as exc:
                bindings = []
                lines = [f"[System] Detector binding error: {exc}"]
            else:
                lines = hardware_test_lines(
                    bindings,
                    settings.baudrate,
                    settings.serial_timeout,
                )
        super().__init__("Hardware test", lines, parent)
