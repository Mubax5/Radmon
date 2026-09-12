import socket

from fastapi import FastAPI

from radmon.central_service import ManagedUvicornServer, smoke_server_lifecycle


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


def test_managed_uvicorn_releases_port_after_stop():
    app = FastAPI()
    app.get("/health")(lambda: {"status": "ok"})
    port = _free_port()
    server = ManagedUvicornServer(app, "127.0.0.1", port)
    server.start(timeout=5)
    assert server.running
    server.stop(timeout=5)
    probe = socket.socket()
    try:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        probe.close()


def test_managed_uvicorn_stop_is_idempotent():
    app = FastAPI()
    port = _free_port()
    server = ManagedUvicornServer(app, "127.0.0.1", port)
    server.start(timeout=5)
    server.stop(timeout=5)
    server.stop(timeout=5)
    assert not server.running


def test_smoke_server_lifecycle_completes_without_leaking_listener():
    smoke_server_lifecycle()
