from __future__ import annotations

import socket
import threading
import time

from fastapi import FastAPI
import uvicorn


class ManagedUvicornServer:
    """Own one Uvicorn server and its worker thread explicitly."""

    def __init__(self, app, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=self.port,
                reload=False,
                log_config=None,
            )
        )
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
            and self._server.started
        )

    def start(self, timeout: float = 30.0) -> None:
        if self.running:
            return
        self._server.should_exit = False
        self._server.force_exit = False
        self._thread = threading.Thread(
            target=self._server.run,
            name="radmon-central-api",
            daemon=False,
        )
        self._thread.start()
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if self._server.started:
                return
            if not self._thread.is_alive():
                break
            time.sleep(0.05)
        self.stop(timeout=1.0)
        raise RuntimeError(f"central API gagal start pada {self.host}:{self.port}")

    def stop(self, timeout: float = 15.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._server.should_exit = True
        thread.join(timeout=max(0.1, timeout))
        if thread.is_alive():
            self._server.force_exit = True
            thread.join(timeout=2.0)
        if thread.is_alive():
            raise RuntimeError("central API gagal berhenti")
        self._thread = None


def _free_local_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def smoke_server_lifecycle() -> None:
    """Exercise packaged server imports/start/stop without production DB access."""
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    server = ManagedUvicornServer(app, "127.0.0.1", _free_local_port())
    server.start(timeout=5.0)
    server.stop(timeout=5.0)
