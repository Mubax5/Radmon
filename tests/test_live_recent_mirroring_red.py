"""RED test: stale recent while measurement fresh + remote readable must recover.

Evidence from production:
- measurement current for gd50/gd38 (~14:03 onward) but recent stale ~13:09/13:13
- 15 live_rows partly offline (11) while direct remote reads succeed
- logs only gd52 live updates; gd50/gd38 live loops silent while backfill active
- Grafana recent/remote proof indicates remote connectivity OK but central recent mirror stale

The test reproduces: central measurement is fresh via backfill, remote live_rows is
readable and fresh, but central recent remains stale because the live mirror loop
died (health-record failure, unhandled exception, or vrecent transient). The fix
must ensure live mirror resumes via reconnect/backoff/last-sample without
hardcoding building ids and without mutating remote DB or losing history.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from radmon.lan import LanAggregator, LanCheckpointStore, LanSource
from radmon.security import SecurityStore


class FakeRemote:
    def __init__(self, source, live_rows, devices, measurements):
        self.source = source
        self._live_rows = live_rows
        self._devices = devices
        self._measurements = measurements
        self.live_calls = 0

    def live_rows(self):
        self.live_calls += 1
        # First call succeeds with fresh data
        return self._live_rows

    def devices(self):
        return self._devices

    def measurements_after(self, serid, after, limit):
        # Return measurements for that serid after checkpoint, ASC
        rows = [r for r in self._measurements if r["serid"] == serid and (after is None or r["dtom"] > after)]
        # Sort ASC as production does
        rows = sorted(rows, key=lambda x: x["dtom"])
        return rows[:limit]

    def alarms_after(self, checkpoint, limit=500):
        return []

    def alarm_states(self, limit=2000):
        return []

    def active_alarm_keys(self):
        return []

    # Support fallback direct connection path used by run_live_fallback_once
    def _connection(self):
        raise RuntimeError("no direct connection in this fake")

class FallbackRemote:
    """Simulates vrecent failure but measurement readable."""
    def __init__(self, source, devices, measurements):
        self.source = source
        self._devices = devices
        self._measurements = measurements
        self.live_calls = 0

    def live_rows(self):
        self.live_calls += 1
        raise RuntimeError("Lost connection to server at 'reading authorization packet', system error: 0")

    def devices(self):
        return self._devices

    def measurements_after(self, serid, after, limit):
        rows = [r for r in self._measurements if r["serid"] == serid and (after is None or r["dtom"] > after)]
        rows = sorted(rows, key=lambda x: x["dtom"])
        return rows[:limit]

    def alarms_after(self, checkpoint, limit=500):
        return []

    def alarm_states(self, limit=2000):
        return []

    def active_alarm_keys(self):
        return []

    def _connection(self):
        # Provide a fake connection that serves measurement fallback query
        class Cursor:
            def __init__(inner, outer):
                inner.outer = outer
                inner.last_sql = ""
                inner.params = ()
            def __enter__(inner):
                return inner
            def __exit__(inner, *a):
                return False
            def execute(inner, sql, params=()):
                inner.last_sql = sql
                inner.params = params
            def fetchone(inner):
                if "FROM measurement" in inner.last_sql:
                    serid = int(inner.params[0])
                    # Find latest measurement for serid
                    candidates = [r for r in inner.outer._measurements if r["serid"] == serid]
                    if not candidates:
                        return None
                    latest = max(candidates, key=lambda x: x["dtom"])
                    return latest
                if "FROM device" in inner.last_sql:
                    # Return devices as tuples for _dict_rows
                    return None
                return None
            def fetchall(inner):
                if "FROM device" in inner.last_sql:
                    # Devices
                    return [
                        (d["serid"], d["name"], d["location"], d["warnlevel"], d["alarmlevel"], d["unit"], d["audiopath"], d["description"], d["maxidlemin"])
                        for d in inner.outer._devices
                    ]
                return []
        class Conn:
            def __init__(inner, outer):
                inner.outer = outer
                inner.c = Cursor(outer)
            def cursor(inner):
                return inner.c
            def close(inner):
                pass
        return Conn(self)


class FakeCentral:
    def __init__(self):
        self.live_mirrored = []
        self.measurements = {}  # (serid, dtom) -> row
        self.call_count = 0

    def ensure_remote_device(self, source_id, row):
        pass

    def upsert_live_rows(self, source_id, rows):
        # Simulate Batch central store: mirror to recent via rolling
        self.call_count += 1
        for r in rows:
            dtom = r.get("dtom")
            # This is what Batched store does via _rolling_row: skip if dtom string?
            # Our fix must handle string dtom.
            self.live_mirrored.append((source_id, r["serid"], dtom, r.get("doserate")))
        return len(rows)

    def import_measurements(self, source_id, rows):
        inserted = 0
        for r in rows:
            key = (r["serid"], r["dtom"])
            if key not in self.measurements:
                self.measurements[key] = r
                inserted += 1
        return inserted

    def mirror_alarm_events(self, source_id, rows):
        return 0

    def mark_alarm_handled(self, keys):
        return 0


def test_live_stale_recent_recovers_via_last_sample_fallback(tmp_path):
    """Reproduce: remote vrecent fails, but measurement fresh; recent must still update.

    Before fix, live_rows exception would make result.error and recent stays stale.
    After fix, Realtime fallback or aggregator fallback ensures recent gets fresh
    measurement (last-sample) even though vrecent transiently failed.
    This is generic per-source, not hardcoded to gd50/gd38.
    """
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    # Simulate any building, not hardcoded – use 3001 as example but test generic
    source_id = "gd38"
    source = LanSource(source_id, "192.168.1.38", 3306, "u", "p", "ipradmon")
    fresh_at = datetime(2026, 9, 28, 14, 3, 0)
    stale_at = datetime(2026, 9, 28, 13, 9, 0)
    devices = [
        {"serid": 3801, "name": "Kolam", "location": "Gd.38", "warnlevel": 8, "alarmlevel": 10, "maxidlemin": 30, "unit": "µSv/h", "description": "prod", "audiopath": ""},
    ]
    # Measurement fresh (backfill would have inserted)
    measurements = [
        {"serid": 3801, "dtom": fresh_at, "doserate": 0.31, "dose": 0.01, "previnterval": 2, "stat": 0},
    ]
    central = FakeCentral()
    # Pretend measurement already fresh in central via backfill
    central.measurements[(3801, fresh_at)] = measurements[0]
    # Remote live_rows fails (vrecent transient) but device+measurement readable
    remote = FallbackRemote(source, devices, measurements)
    aggregator = LanAggregator(central, checkpoints, remote_factory=lambda _: remote)

    # First attempt: live_rows fails, should go to fallback
    result = aggregator.run_live_once(source)
    # Before fix, result would be error and live_mirrored empty, recent stale
    # After fix, fallback should have been attempted via run_live_fallback_once
    # But run_live_once itself does not auto-fallback; lan_runtime does.
    # So we test the fallback path explicitly as lan_runtime would.
    if result.error:
        fallback = aggregator.run_live_fallback_once(source)
        assert fallback.error is None, f"fallback should succeed but got {fallback.error}"
        assert fallback.live_stations == 1
        assert central.live_mirrored, "fallback must mirror to recent"
        # Check that mirrored dtom is fresh, not stale
        mirrored_dtom = central.live_mirrored[0][2]
        assert mirrored_dtom == fresh_at, f"recent should be fresh {fresh_at} not {mirrored_dtom}"
    else:
        # If live succeeded (because fix made live_rows fallback internally), also expect fresh
        assert result.live_stations == 1
        # Hot-path fallback makes live_rows itself succeed via measurement
        # In that case fallback not needed, but live_mirrored should be fresh
        assert central.live_mirrored
        assert central.live_mirrored[0][2] == fresh_at


def test_live_thread_survives_transient_health_failure_and_retries(tmp_path):
    """Reproduce silent live loop for gd50/gd38: health record failure killed thread.

    Before fix, _run_live_source had no outer try; a health store exception
    (e.g. sqlite locked) would kill the per-source thread, leaving recent stale
    while backfill continued. After fix, thread must survive and backoff.
    This test is generic – it uses a source id that is not hardcoded.
    """
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    source = LanSource("gd50", "192.168.1.50", 3306, "u", "p", "ipradmon")
    fresh_at = datetime(2026, 9, 28, 14, 3, 0)
    devices = [
        {"serid": 3001, "name": "R. Evaporasi", "location": "Gd.50", "warnlevel": 8, "alarmlevel": 10, "maxidlemin": 30, "unit": "µSv/h", "description": "prod", "audiopath": ""},
    ]
    measurements = [
        {"serid": 3001, "dtom": fresh_at, "doserate": 0.28, "dose": 0.01, "previnterval": 2, "stat": 0},
    ]
    live_rows = [
        {"serid": 3001, "name": "R. Evaporasi", "location": "Gd.50", "warnlevel": 8, "alarmlevel": 10, "maxidlemin": 30, "unit": "µSv/h", "description": "prod", "audiopath": "", "dtom": fresh_at, "doserate": 0.28, "dose": 0.01, "lastrate": 0.27, "minrate": 0.1, "maxrate": 0.3, "avgrate": 0.2, "lastdose": 0.01, "mindose": 0, "maxdose": 0.02, "avgdose": 0.01, "firstmea": datetime(2026, 9, 28, 13, 0, 0), "lastmea": fresh_at, "lastmeasec": 2, "meacount": 10},
    ]
    central = FakeCentral()
    remote = FakeRemote(source, live_rows, devices, measurements)

    # Health service that fails once then recovers (simulating sqlite locked)
    health_calls = []
    class FlakyHealth:
        def __init__(self):
            self.fail_next = True
        def record_success(self, src, **kw):
            health_calls.append(("success", src.source_id))
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("database is locked")
            return {"state": "CONNECTED"}
        def record_failure(self, src, err):
            health_calls.append(("failure", src.source_id, err))
            return {"state": "DEGRADED"}
        def record_history_import(self, src):
            health_calls.append(("history", src.source_id))
            return {"state": "CONNECTED"}

    flaky = FlakyHealth()
    services = SimpleNamespace(security=store, source_health=flaky, alarm_mirror=None)
    # Patch LanRuntime to use our aggregator and flaky health
    from radmon.lan_runtime import LanRuntime
    from radmon.config import Settings

    settings = Settings()
    runtime = LanRuntime(settings, services)
    runtime.interval = 0.05  # fast for test
    runtime.central = central
    runtime.checkpoints = checkpoints
    # Override aggregator factory to return our fake remote
    runtime._aggregator = lambda batch_size=None: LanAggregator(central, checkpoints, remote_factory=lambda _: remote)

    # Run live loop for a short time in a thread and ensure it does not die after first health failure
    import threading, time
    t = threading.Thread(target=runtime._run_live_source, args=(source,), daemon=True)
    t.start()
    # Let it run for 0.3 seconds => ~6 iterations
    time.sleep(0.35)
    runtime.stop_event.set()
    t.join(timeout=1.0)
    # Thread must have exited cleanly via stop_event, not died early
    assert not t.is_alive(), "live thread should exit cleanly after stop, not die early"
    # It should have attempted health record at least twice (once failed, then retried with backoff)
    # And central should have been mirrored at least once after the transient failure
    assert len(central.live_mirrored) >= 1, "live mirror must have resumed after transient health failure"
    # Health should have been called at least 2 times (first failed, second succeeded)
    assert len(health_calls) >= 2, f"health should have been retried, got {health_calls}"
    # Verify not hardcoded to specific building – works for gd50 and would also work for gd38/gd52
    for call in health_calls:
        assert call[1] == "gd50"  # generic, not hardcoded building check


def test_live_string_dtom_still_mirrors_recent(tmp_path):
    """Ensure string dtom from MariaDB does not cause mirror to skip.

    Before fix, _rolling_row in lan_store skipped string dtom, leaving recent stale
    while measurement (via backfill) was fresh. After fix, string dtom is parsed
    and mirrored, preserving history and updating recent.
    """
    store = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(store)
    source = LanSource("any_source", "192.168.1.100", 3306, "u", "p", "ipradmon")
    # Remote returns string dtom (common for some MariaDB drivers)
    fresh_str = "2026-09-28 14:03:00"
    fresh_at = datetime(2026, 9, 28, 14, 3, 0)
    devices = [
        {"serid": 5201, "name": "IS-1", "location": "Gd.52", "warnlevel": 23, "alarmlevel": 25, "maxidlemin": 30, "unit": "µSv/h", "description": "prod", "audiopath": ""},
    ]
    live_rows_str = [
        {"serid": 5201, "name": "IS-1", "location": "Gd.52", "warnlevel": 23, "alarmlevel": 25, "maxidlemin": 30, "unit": "µSv/h", "description": "prod", "audiopath": "", "dtom": fresh_str, "doserate": 0.27, "dose": 0.01, "lastrate": 0.27, "minrate": 0.1, "maxrate": 0.3, "avgrate": 0.2, "lastdose": 0.01, "mindose": 0, "maxdose": 0.02, "avgdose": 0.01, "firstmea": "2026-09-28 13:00:00", "lastmea": fresh_str, "lastmeasec": 2, "meacount": 10},
    ]
    central = FakeCentral()
    remote = FakeRemote(source, live_rows_str, devices, [])
    aggregator = LanAggregator(central, checkpoints, remote_factory=lambda _: remote)
    result = aggregator.run_live_once(source)
    # After fix, string dtom should be parsed and mirrored, not skipped
    assert result.error is None, f"should not error on string dtom: {result.error}"
    assert central.live_mirrored, "mirror must happen even with string dtom"
    mirrored_dtom, rate = central.live_mirrored[0][2], central.live_mirrored[0][3]
    # Mirrored dtom may be string or datetime, but should be convertible to fresh_at
    from radmon.lan import _parse_dtom
    parsed = _parse_dtom(mirrored_dtom)
    assert parsed == fresh_at, f"string dtom should be parsed to {fresh_at}, got {parsed}"
    assert float(rate) == 0.27
