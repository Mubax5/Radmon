from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from radmon.central_service import CentralService
from radmon.config import Settings


def test_slow_archive_reconciliation_does_not_block_api_readiness():
    """A large archive scan must start only after the API listener is ready."""
    api_started = threading.Event()
    reconcile_started = threading.Event()
    release_reconcile = threading.Event()

    class SlowArchiveCatalog:
        def reconcile(self):
            assert api_started.is_set()
            reconcile_started.set()
            release_reconcile.wait(2.0)
            return []

    class ReadyApi:
        running = False

        def start(self, timeout=30):
            self.running = True
            api_started.set()

        def stop(self, timeout=15):
            self.running = False

    runtime = SimpleNamespace(
        app=object(),
        services=SimpleNamespace(alarm_suppression=None),
        archive_catalog=SlowArchiveCatalog(),
        lan_runtime=None,
    )
    service = CentralService(
        Settings(lan_enabled=False),
        runtime_factory=lambda settings: runtime,
        api_factory=lambda app, host, port: ReadyApi(),
    )

    started_at = time.monotonic()
    service.start()
    elapsed = time.monotonic() - started_at

    try:
        assert elapsed < 1.0
        assert api_started.is_set()
        assert reconcile_started.wait(1.0)
    finally:
        release_reconcile.set()
        service.stop()
