from datetime import datetime, timezone

from radmon.lan import LanSource
from radmon.security import SecurityStore
from radmon.source_health import SourceHealthService


def test_source_health_transitions_and_messages(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    service = SourceHealthService(store, offline_after_failures=2)
    source = LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon")

    first = service.record_success(source, live=True, alarm=True, history=True)
    assert first["state"] == "CONNECTED"
    assert first["transition_message"] is None

    degraded = service.record_failure(source, "timeout")
    assert degraded["state"] == "DEGRADED"
    assert "DEGRADED" in degraded["transition_message"]

    offline = service.record_failure(source, "timeout")
    assert offline["state"] == "OFFLINE"
    assert "OFFLINE" in offline["transition_message"]

    recovered = service.record_success(source, live=True, alarm=True, history=False)
    assert recovered["state"] == "RECOVERED"
    assert "RECOVERED" in recovered["transition_message"]

    healthy = service.record_success(source, live=True, alarm=True, history=True)
    assert healthy["state"] == "CONNECTED"
    assert healthy["transition_message"] is None

    rows = service.list_states()
    assert rows[0]["source_id"] == "gd52"
    assert rows[0]["host"] == "192.168.1.52"
    assert rows[0]["consecutive_failures"] == 0


def test_source_health_timestamps_are_persisted(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    service = SourceHealthService(store)
    source = LanSource("gd38", "192.168.1.38", 3306, "u", "p", "ipradmon")
    service.record_success(source, live=True, alarm=False, history=False)
    row = service.list_states()[0]
    assert datetime.fromisoformat(row["last_success"]).tzinfo is not None


def test_history_import_marker_does_not_recover_degraded_live_state(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    service = SourceHealthService(store, offline_after_failures=3)
    source = LanSource("gd50", "192.168.1.50", 3306, "u", "p", "ipradmon")
    service.record_success(source, live=True, alarm=True, history=False)
    degraded = service.record_failure(source, "live timeout")
    assert degraded["state"] == "DEGRADED"
    assert degraded["consecutive_failures"] == 1

    history = service.record_history_import(source)

    assert history["state"] == "DEGRADED"
    assert history["consecutive_failures"] == 1
    assert history["last_error"] == "live timeout"
    assert datetime.fromisoformat(history["last_history_import"]).tzinfo is not None
