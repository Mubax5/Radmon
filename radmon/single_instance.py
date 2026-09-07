from __future__ import annotations

import socket


class SingleInstanceLock:
    def __init__(self, port: int) -> None:
        self.port = int(port)
        self._socket: socket.socket | None = None

    def acquire(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            sock.bind(("127.0.0.1", self.port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._socket = sock
        return True

    def release(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
