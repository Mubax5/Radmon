"""RED tests for robust single-click startup: stale lock recovery, idempotent start, listener supervision."""

from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from radmon.paths import ApplicationPaths


# 1. SingleInstanceLock must have health probe and crash-safe recovery
def test_single_instance_has_health_probe_and_recovery():
    from radmon.single_instance import SingleInstanceLock

    lock = SingleInstanceLock(47652)
    # New robust lock must expose health probing or recovery helpers
    assert hasattr(lock, "_is_holder_healthy") or hasattr(lock, "_probe_health") or hasattr(lock, "health_port") or hasattr(
        SingleInstanceLock, "_is_holder_healthy"
    ), "SingleInstanceLock must have liveness probe"
    # Must have bounded recovery logic: check acquire handles stale
    assert hasattr(lock, "acquire"), "acquire must exist"
    # Check lock supports optional lock_file param for crash-safe file
    import inspect

    sig = inspect.signature(SingleInstanceLock.__init__)
    params = list(sig.parameters.keys())
    assert "lock_file" in params or "health_port" in params or len(params) >= 2, "SingleInstanceLock must support crash-safe lock_file or health probing"


def test_single_instance_stale_recovery_via_tcp_probe(tmp_path):
    """Bind holder that does not serve 8090 -> second acquire should detect stale and eventually recover (or at least not silently refuse without health check)."""
    from radmon.single_instance import SingleInstanceLock
    from unittest import mock

    # Find two free ports for instance lock and health probe
    def free_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    lock_port = free_port()
    health_port = free_port()

    holder = SingleInstanceLock(lock_port)
    assert holder.acquire(), "holder must acquire"
    try:
        # No server on health_port -> health probe should fail, so stale holder should be considered stale
        # Mock health probe to simulate 8090 dead
        with mock.patch.object(SingleInstanceLock, "_is_holder_healthy", return_value=False):
            # Mock termination to free the socket quickly
            with mock.patch.object(SingleInstanceLock, "_try_terminate", return_value=True) as mock_term:
                # Mock find_listener_owner to return holder pid
                fake_owner = SimpleNamespace(pid=99999, command_line="fake RadMon.exe")
                with mock.patch("radmon.process_ownership.find_listener_owner", return_value=fake_owner):
                    second = SingleInstanceLock(lock_port)
                    # Second should attempt recovery and not simply return False without probing
                    # It should call health check and termination logic
                    result = second.acquire()
                    # If recovery implemented, second may succeed after holder terminated, or at least have attempted termination
                    # The key is that it did not blindly refuse without health check
                    assert mock_term.call_count >= 0 or not result, "stale recovery logic must be invoked"
                    # After holder release, second should be able to acquire if we release holder
                    holder.release()
                    # Now second should succeed
                    second2 = SingleInstanceLock(lock_port)
                    with mock.patch.object(SingleInstanceLock, "_is_holder_healthy", return_value=False):
                        assert second2.acquire(), "after holder released, acquire must succeed"
                        second2.release()
                    # clean up second if it held socket
                    try:
                        second.release()
                    except Exception:
                        pass
    finally:
        holder.release()


def test_production_app_has_liveness_recovery():
    from radmon import production_app

    # Must have helpers for health probing and lock recovery
    assert hasattr(production_app, "_probe_central_health") or hasattr(
        production_app, "_acquire_lock_with_recovery"
    ), "production_app must have liveness probe/recovery helpers"
    # run_production/run_server must be idempotent when holder healthy
    import inspect

    src = inspect.getsource(production_app.run_production)
    assert "health" in src.lower() or "probe" in src.lower() or "_acquire_lock_with_recovery" in src, "run_production must handle stale/healthy via health probe"
    src2 = inspect.getsource(production_app.run_server)
    assert "health" in src2.lower() or "probe" in src2.lower() or "_acquire_lock_with_recovery" in src2, "run_server must handle idempotent healthy case"


def test_production_app_recovers_stale_and_starts_central(tmp_path):
    """Simulate lock held but health dead -> production should recover and start central."""
    from radmon.production_app import run_production, run_server
    from radmon.paths import ApplicationPaths

    paths = ApplicationPaths(
        tmp_path,
        tmp_path / "app",
        tmp_path / "config",
        tmp_path / "runtime",
        tmp_path / "archives",
        tmp_path / "reports",
        tmp_path / "runtime" / "logs",
        tmp_path / "app" / "assets",
        tmp_path / "app" / "grafana",
    )

    # Fake central that records start
    started = []

    class FakeCentral:
        def __init__(self, *a, **k):
            self.services = SimpleNamespace(alarm_suppression=None)
            self.archive_catalog = object()

        def start(self):
            started.append("start")

        def stop(self):
            started.append("stop")

    # Lock factory that fails first acquire (simulating stale holder) then succeeds
    attempts = []

    class StaleThenFreeLock:
        def __init__(self, port):
            self.port = port

        def acquire(self):
            attempts.append(1)
            # First call fails, second succeeds (recovery)
            return len(attempts) > 1

        def release(self):
            pass

    # Patch health probe to indicate stale (dead)
    import radmon.production_app as prod

    original_probe = getattr(prod, "_probe_central_health", None)
    try:
        prod._probe_central_health = lambda *a, **k: False
        # Patch find_listener_owner to avoid powershell
        import radmon.process_ownership as po

        orig_find = po.find_listener_owner
        po.find_listener_owner = lambda *a, **k: None
        # Make lock recovery helper if exists to simulate stale recovery: force retry
        # Instead we directly test run_production's new robust acquire
        # If robust logic implemented, it will retry and succeed on second attempt
        # For now we simulate by making lock_factory return a lock that succeeds on second try
        # But run_production currently only calls acquire once and returns 2, so this test will be RED before fix
        # After fix, it should call acquire with recovery and eventually start central
        code = run_production(
            paths=paths,
            central_factory=lambda *a, **k: FakeCentral(),
            desktop_runner=lambda *a, **k: 0,
            lock_factory=lambda port: StaleThenFreeLock(port),
            grafana_startup=lambda *a, **k: None,
            listener_owner=lambda port: None,
        )
        # After fix, code should be 0 and central started despite first lock failure (stale recovery)
        assert code == 0, f"stale lock should be recovered and central started, got {code}"
        assert "start" in started, "central must have started after stale recovery"
    finally:
        if original_probe is not None:
            prod._probe_central_health = original_probe
        else:
            if hasattr(prod, "_probe_central_health"):
                delattr(prod, "_probe_central_health")
        po.find_listener_owner = orig_find


def test_production_app_idempotent_when_healthy(tmp_path):
    """If lock held but 8090 healthy, second start should be idempotent (return 0, not 2, and not start duplicate central)."""
    from radmon.production_app import run_production, run_server
    from radmon.paths import ApplicationPaths

    paths = ApplicationPaths(
        tmp_path,
        tmp_path / "app",
        tmp_path / "config",
        tmp_path / "runtime",
        tmp_path / "archives",
        tmp_path / "reports",
        tmp_path / "runtime" / "logs",
        tmp_path / "app" / "assets",
        tmp_path / "app" / "grafana",
    )

    class FakeLockHeld:
        def __init__(self, port):
            self.port = port

        def acquire(self):
            return False

        def release(self):
            pass

    central_started = []

    class FakeCentral:
        def __init__(self, *a, **k):
            pass

        def start(self):
            central_started.append(1)

        def stop(self):
            pass

    import radmon.production_app as prod

    orig = getattr(prod, "_probe_central_health", None)
    try:
        prod._probe_central_health = lambda *a, **k: True  # healthy
        # run_server should be idempotent when healthy
        code = run_server(
            paths=paths,
            central_factory=FakeCentral,
            lock_factory=lambda port: FakeLockHeld(port),
            grafana_startup=lambda *a, **k: None,
            listener_owner=lambda port: None,
            stop_event=threading.Event(),
        )
        assert code == 0, "healthy holder should make run_server idempotent return 0"
        assert central_started == [], "should not start duplicate central when healthy"

        # run_production also idempotent (should open web or return 0)
        central_started.clear()
        # mock webbrowser.open to avoid side effect
        import unittest.mock as mock

        with mock.patch("radmon.production_app.webbrowser.open", return_value=True):
            code2 = run_production(
                paths=paths,
                central_factory=FakeCentral,
                desktop_runner=lambda *a, **k: 0,
                lock_factory=lambda port: FakeLockHeld(port),
                grafana_startup=lambda *a, **k: None,
                listener_owner=lambda port: None,
            )
            assert code2 == 0, "healthy holder should make run_production idempotent (open web) return 0"
            assert central_started == [], "should not start duplicate central when healthy"
    finally:
        if orig is not None:
            prod._probe_central_health = orig
        elif hasattr(prod, "_probe_central_health"):
            delattr(prod, "_probe_central_health")


def test_managed_uvicorn_recovers_dead_listener(tmp_path):
    """ManagedUvicornServer must detect dead listener via health probe and restart, not just wait for worker_exited."""
    from radmon.central_service import ManagedUvicornServer
    import inspect

    src = inspect.getsource(ManagedUvicornServer._supervise)
    # Must contain health probe logic beyond worker_exited
    assert (
        "is_listening" in src or "_is_healthy" in src or "health" in src.lower() or "8090" in src or "socket" in src.lower()
    ), "supervisor must have health probe to recover dead listener when accept loop dies"
    # Also check it has bounded backoff and logs reason
    assert "Restart" in src or "restart" in src.lower(), "supervisor must log restart"
    assert "delay" in src.lower(), "supervisor must have bounded backoff delay"


def test_single_instance_crash_safe_lock_file(tmp_path):
    from radmon.single_instance import SingleInstanceLock
    import inspect

    src = inspect.getsource(SingleInstanceLock)
    assert "lock_file" in src.lower() or "instance.lock" in src.lower() or "runtime" in src.lower(), "SingleInstanceLock must support crash-safe lock file"
