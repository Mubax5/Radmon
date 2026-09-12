import socket
from types import SimpleNamespace

from fastapi import FastAPI

from radmon.central_service import CentralService, ManagedUvicornServer, smoke_server_lifecycle
from radmon.config import Settings


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


class FakeLanRuntime:
    def __init__(self, events):
        self.events = events

    def start(self):
        self.events.append("lan-start")

    def stop(self):
        self.events.append("lan-stop")


class FakeApi:
    def __init__(self, app, host, port, events):
        self.events = events

    @property
    def running(self):
        return True

    def start(self, timeout=30):
        self.events.append("api-start")

    def stop(self, timeout=15):
        self.events.append("api-stop")


def test_central_service_stops_lan_before_api():
    events = []
    runtime = SimpleNamespace(
        app=object(),
        services=object(),
        archive_catalog=object(),
        lan_runtime=FakeLanRuntime(events),
    )
    service = CentralService(
        Settings(lan_enabled=True),
        runtime_factory=lambda settings: runtime,
        api_factory=lambda app, host, port: FakeApi(app, host, port, events),
    )
    service.start()
    service.stop()
    assert events == ["lan-start", "api-start", "lan-stop", "api-stop"]


def test_central_service_cleans_lan_when_api_start_fails():
    events = []
    runtime = SimpleNamespace(
        app=object(),
        services=object(),
        archive_catalog=object(),
        lan_runtime=FakeLanRuntime(events),
    )

    class FailingApi(FakeApi):
        def start(self, timeout=30):
            self.events.append("api-start")
            raise RuntimeError("boom")

    service = CentralService(
        Settings(lan_enabled=True),
        runtime_factory=lambda settings: runtime,
        api_factory=lambda app, host, port: FailingApi(app, host, port, events),
    )
    try:
        service.start()
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected api startup failure")
    assert events == ["lan-start", "api-start", "lan-stop"]
