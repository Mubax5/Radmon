import socket
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.central_api import create_central_app
from radmon.central_service import CentralService, ManagedUvicornServer, SuppressionExpiryScheduler, smoke_server_lifecycle
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


def test_managed_uvicorn_supervises_unexpected_listener_exit_without_duplicate_workers():
    app = FastAPI()
    exits: list[threading.Event] = []

    class ControlledServer:
        def __init__(self):
            self.started = False
            self.should_exit = False
            self.force_exit = False
            self.exit = threading.Event()
            exits.append(self.exit)

        def run(self):
            self.started = True
            while not self.should_exit and not self.force_exit and not self.exit.wait(0.01):
                pass
            self.started = False

    created = []

    def factory(app, host, port):
        server = ControlledServer()
        created.append(server)
        return server

    server = ManagedUvicornServer(app, "127.0.0.1", _free_port(), server_factory=factory)
    server.start(timeout=1)
    server.start(timeout=1)
    assert len(created) == 1

    exits[0].set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(created) < 2:
        time.sleep(0.02)

    assert len(created) == 2
    assert server.running
    assert server.status["failure_count"] == 1
    server.stop(timeout=1)


def test_managed_uvicorn_restarts_after_worker_exception():
    app = FastAPI()
    release_failure = threading.Event()
    created = []

    class FailingServer:
        def __init__(self, fails):
            self.fails = fails
            self.started = False
            self.should_exit = False
            self.force_exit = False

        def run(self):
            self.started = True
            if self.fails:
                release_failure.wait(1)
                self.started = False
                raise OSError("simulated accept failure")
            while not self.should_exit and not self.force_exit:
                time.sleep(0.01)
            self.started = False

    def factory(app, host, port):
        server = FailingServer(not created)
        created.append(server)
        return server

    server = ManagedUvicornServer(app, "127.0.0.1", _free_port(), server_factory=factory)
    server.start(timeout=1)
    release_failure.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(created) < 2:
        time.sleep(0.02)

    assert len(created) == 2
    assert server.running
    assert "OSError: simulated accept failure" in str(server.status["last_error"])
    server.stop(timeout=1)


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


def test_expiry_scheduler_runs_periodically_without_lan_runtime_and_stops_cleanly():
    calls = []

    class StopAfterOneWait:
        def __init__(self):
            self.waits = []
            self.stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, interval):
            self.waits.append(interval)
            self.stopped = True
            return True

        def set(self):
            self.stopped = True

    stop_event = StopAfterOneWait()
    scheduler = SuppressionExpiryScheduler(lambda: calls.append("expire"), interval=17.0, stop_event=stop_event)
    scheduler._run()

    assert calls == ["expire"]
    assert stop_event.waits == [17.0]


def test_expiry_scheduler_logs_failures_recovers_and_stops_cleanly(caplog):
    calls = []
    second_call = threading.Event()

    def expire_due():
        calls.append("expire")
        if len(calls) == 1:
            raise RuntimeError("durable expiry unavailable")
        second_call.set()

    scheduler = SuppressionExpiryScheduler(expire_due, interval=0.01)
    scheduler.start()
    assert second_call.wait(1.0)
    scheduler.stop(timeout=1.0)

    assert calls == ["expire", "expire"]
    assert scheduler.status["state"] == "OK"
    assert scheduler.status["failure_count"] == 1
    assert any("suppression expiry scheduler failed" in record.message for record in caplog.records)


def test_central_health_reports_degraded_expiry_scheduler():
    class Repository:
        def ping(self):
            return True

    app = create_central_app(Repository(), Settings())
    app.state.radmon_suppression_expiry_scheduler = SimpleNamespace(status={
        "state": "DEGRADED", "last_error": "RuntimeError: durable expiry unavailable", "failure_count": 1,
    })

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["suppression_expiry"]["failure_count"] == 1


def test_central_service_owns_expiry_scheduler_when_lan_is_disabled():
    events = []

    class Scheduler:
        def start(self):
            events.append("expiry-start")

        def stop(self):
            events.append("expiry-stop")

    runtime = SimpleNamespace(
        app=object(),
        services=SimpleNamespace(alarm_suppression=object()),
        archive_catalog=object(),
        lan_runtime=None,
    )
    service = CentralService(
        Settings(lan_enabled=False),
        runtime_factory=lambda settings: runtime,
        api_factory=lambda app, host, port: FakeApi(app, host, port, events),
        expiry_scheduler_factory=lambda suppression: Scheduler(),
    )
    service.start()
    service.stop()

    assert events == ["expiry-start", "api-start", "expiry-stop", "api-stop"]
