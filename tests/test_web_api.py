from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.security import Role, SecurityStore
from radmon.web_api import attach_web_api_routes
from radmon.secure_api import SESSION_COOKIE


class FakeRepository:
    def stations(self):
        return [
            {"serid": 5201, "name": "IS-1", "location": "Gd.52", "description": "Detector room", "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "uSv/h"},
            {"serid": 5202, "name": "IS-1 Koridor", "location": "Gd.52", "description": "Corridor detector", "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "uSv/h"},
            {"serid": 5203, "name": "IS-1 Cadangan", "location": "Gd.52", "description": "Offline detector", "warnlevel": 23.0, "alarmlevel": 25.0, "unit": "uSv/h"},
        ]

    def latest(self, serid: int):
        if serid == 5201:
            return {"serid": 5201, "dtom": "2026-09-13T04:00:00", "doserate": 10.0, "dose": 1.0, "previnterval": 2, "stat": 0}
        if serid == 5202:
            return {"serid": 5202, "dtom": "2026-09-13T04:00:00", "doserate": 26.0, "dose": 1.0, "previnterval": 2, "stat": 0}
        return None

    def history(self, serid: int, limit: int = 240):
        if serid in (5201, 5202):
            return [{"serid": serid, "dtom": "2026-09-13T04:00:00", "doserate": 10.0, "dose": 1.0, "previnterval": 2, "stat": 0}][:limit]
        return []


class FakeSourceHealth:
    def list_states(self):
        return [{"source_id": "gd50", "state": "CONNECTED"}]


def make_client(tmp_path, role: Role, *, source_owned_serid: int | None = None, alarm_policy=None):
    security = SecurityStore(tmp_path / f"{role.value}.db")
    username = role.value.lower()
    security.create_user(username, role.value, role, "Password123!", "2468")
    if source_owned_serid is not None:
        security.resolve_station("gd52", source_owned_serid)
    token = security.create_session(username, 3600)
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=FakeRepository(), source_health=FakeSourceHealth(), alarm_policy=alarm_policy)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    return client


def test_anonymous_is_not_a_viewer(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=FakeRepository())
    response = TestClient(app).get("/api/v1/web/overview")
    assert response.status_code == 401


def test_authenticated_viewer_can_read_overview_and_history(tmp_path):
    client = make_client(tmp_path, Role.VIEWER)
    overview = client.get("/api/v1/web/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["role"] == "Viewer"
    assert body["counts"]["normal"] == 1
    assert body["counts"]["alarm"] == 1
    assert {item["serid"] for item in body["stations"]} == {5201, 5202, 5203}

    detail = client.get("/api/v1/web/stations/5203")
    assert detail.status_code == 200
    assert detail.json()["description"] == "Offline detector"
    assert detail.json()["offline_description"] == "Offline detector"
    assert detail.json()["offline_context"] == "Offline detector"
    assert detail.json()["offline_reason"] == "Belum ada measurement dari perangkat"
    assert detail.json()["latest_timestamp"] is None

    history = client.get("/api/v1/web/stations/5201/history?limit=50")
    assert history.status_code == 200
    assert history.json()[0]["serid"] == 5201


def test_offline_history_uses_bounded_genuine_cache_with_original_timestamps(tmp_path):
    security = SecurityStore(tmp_path / "offline-cache.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    token = security.create_session("viewer", 3600)

    class OfflineRepository:
        def overview_rows(self):
            return [{
                "serid": 5701, "name": "Offline detector", "location": "Gd.57",
                "description": "source offline", "warnlevel": 23.0, "alarmlevel": 25.0,
                "maxidlemin": 30, "unit": "uSv/h", "dtom": "2026-06-23T10:00:00",
                "doserate": 0.17, "dose": 0.01, "previnterval": 2, "stat": 0,
            }]

        def last_readings(self, serid, *, limit):
            assert serid == 5701
            assert limit == 40
            return [
                {"serid": 5701, "dtom": "2026-06-23T10:00:00", "doserate": 0.17, "dose": 0.01, "stat": 0},
                {"serid": 5701, "dtom": "2026-06-23T09:59:58", "doserate": 0.18, "dose": 0.01, "stat": 0},
                {"serid": 5701, "dtom": "2026-06-23T09:59:56", "doserate": 0.16, "dose": 0.01, "stat": 0},
            ]

        def history(self, serid, limit=240):
            raise AssertionError("offline route must not fall back to full history")

    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=OfflineRepository())
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/api/v1/web/stations/5701/history?limit=40")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [row["dtom"] for row in body] == [
        "2026-06-23T10:00:00", "2026-06-23T09:59:58", "2026-06-23T09:59:56"
    ]


def test_station_detail_exposes_source_ownership(tmp_path):
    client = make_client(tmp_path, Role.VIEWER, source_owned_serid=5201)

    detail = client.get("/api/v1/web/stations/5201")

    assert detail.status_code == 200
    assert detail.json()["ownership"] == "source"
    assert detail.json()["source_id"] == "gd52"


def test_station_detail_treats_ambiguous_source_mapping_as_source_owned(tmp_path):
    client = make_client(tmp_path, Role.VIEWER, source_owned_serid=5201)
    # Preserve the existing mapping and add a conflicting source claim.
    security = SecurityStore(tmp_path / f"{Role.VIEWER.value}.db")
    security.resolve_station("gd38", 5201)

    detail = client.get("/api/v1/web/stations/5201")

    assert detail.status_code == 200
    assert detail.json()["ownership"] == "source"
    assert detail.json()["source_id"] == "gd38, gd52"


def test_alarm_history_merges_source_and_policy_rows_with_pagination_without_mutation(tmp_path):
    security = SecurityStore(tmp_path / "history.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    token = security.create_session("viewer", 3600)
    at = datetime(2026, 10, 1, 12, 0, 0)

    class Mirror:
        def __init__(self):
            self.calls = 0
        def list_alarms(self, *, limit):
            self.calls += 1
            return [{"source_id": source_id, "serid": 5702, "remote_serid": 5702,
                      "event_time": at, "level": "ALARM", "is_active": True,
                      "acknowledged_at": None, "pic": "SECRET PIC", "note": "SECRET NOTE",
                      "action": "SECRET ACTION", "operator": "SECRET OP", "user_id": 91,
                      "i_flag": 1} for source_id in ("gd50", "gd52", "gd38")]

    class Policy:
        include_event = True
        class Store:
            def list_suppressions(self, *, limit):
                return [
                    {"suppression_id": "active-1", "serid": 5702, "started_at": "2026-10-08T10:00:00",
                     "expires_at": "2026-10-09T13:00:00", "ended_at": None, "ended_reason": None,
                     "reason": "Pemeliharaan detector"},
                    {"suppression_id": "ended-1", "serid": 5703, "started_at": "2026-10-01T08:00:00",
                     "expires_at": "2026-10-01T09:00:00", "ended_at": "2026-10-01T09:00:00",
                     "ended_reason": "EXPIRED", "reason": "Pengujian"},
                    {"suppression_id": "expired-unprocessed", "serid": 5704, "started_at": "2026-09-30T08:00:00",
                     "expires_at": "2026-09-30T09:00:00", "ended_at": None, "ended_reason": None,
                     "reason": "Pemeliharaan selesai"},
                ]
        store = Store()
        def list_events(self, *, limit):
            return ([{"event_id": "p1", "source_id": "gd52", "serid": 5702,
                      "remote_serid": 5702, "remote_event_time": at,
                      "surfaced_at": at, "kind": "ALARM", "status": "ACTIVE",
                      "action": "POLICY ACTION SECRET", "resolution_reason": "PRIVATE TEXT",
                      "operator_id": "private-user", "secret": "token"}] if self.include_event else [])

    mirror = Mirror()
    policy = Policy()
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=FakeRepository(), alarm_mirror=mirror, alarm_policy=policy)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/api/v1/web/alarm-history?limit=10&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 8
    source_rows = [item for item in body["items"] if item["event_type"] == "source_alarm"]
    assert {item["source_id"] for item in source_rows} == {"gd50", "gd52", "gd38"}
    merged_source = next((item for item in source_rows if item.get("policy_event", {}).get("event_id") == "p1"), None)
    assert merged_source is not None, body["items"]
    assert merged_source["acknowledged"] is False
    assert not {"pic", "note", "action", "operator", "user_id", "i_flag"} & merged_source.keys()
    assert merged_source["source_i_flag"] == 1
    assert not {"action", "resolution_reason", "operator_id", "secret"} & merged_source["policy_event"].keys()
    assert merged_source["suppressed"] is False
    suppression_events = [item for item in body["items"] if item.get("suppression_id")]
    assert {(item["kind"], item["status"]) for item in suppression_events} == {
        ("SUPPRESSION_START", "SUPPRESSED"), ("SUPPRESSION_END", "ENDED"),
    }
    assert {item["suppression_id"] for item in suppression_events} == {"active-1", "ended-1", "expired-unprocessed"}
    assert next(item for item in suppression_events if item["suppression_id"] == "expired-unprocessed" and item["kind"] == "SUPPRESSION_END")["action"] == "EXPIRED"
    assert mirror.calls == 1

    policy.include_event = False
    source_only = client.get("/api/v1/web/alarm-history?limit=10&offset=0").json()
    assert len([item for item in source_only["items"] if item["event_type"] == "source_alarm"]) == 3
    assert all("policy_event" not in item for item in source_only["items"] if item["event_type"] == "source_alarm")


def test_system_diagnostics_are_administrator_only(tmp_path):
    viewer = make_client(tmp_path, Role.VIEWER)
    assert viewer.get("/api/v1/web/system").status_code == 403

    admin = make_client(tmp_path, Role.ADMINISTRATOR)
    response = admin.get("/api/v1/web/system")
    assert response.status_code == 200
    assert response.json()["sources"] == [{"source_id": "gd50", "state": "CONNECTED"}]
    assert response.json()["grafana_admin_url"] == "http://localhost:3300"


def test_viewer_station_read_model_includes_read_only_active_policy_projection(tmp_path):
    class Policy:
        def get_policy(self, serid):
            return {
                "policy_state": "ALARM" if serid == 5202 else "NORMAL",
                "underlying_dose_status": "ALARM" if serid == 5202 else "NORMAL",
                "active_event_id": "alarm-event-5202" if serid == 5202 else None,
                "active_event_lifecycle": "ACTIVE" if serid == 5202 else None,
                "last_event_id": "historical-event-5203" if serid == 5203 else None,
                "last_event_status": "RESOLVED" if serid == 5203 else None,
                "last_event_resolved_at": "2026-09-13T04:01:00Z" if serid == 5203 else None,
                "measured_value": 26.0 if serid == 5202 else None,
                "threshold": 25.0 if serid == 5202 else None,
            }

    viewer = make_client(tmp_path, Role.VIEWER, alarm_policy=Policy())
    items = {item["serid"]: item for item in viewer.get("/api/v1/web/overview").json()["stations"]}
    assert items[5202]["status"] == "alarm"
    assert items[5202]["policy_state"] == "ALARM"
    assert items[5202]["active_event_id"] == "alarm-event-5202"
    assert items[5203]["status"] == "offline"
    assert items[5203]["last_event_status"] == "RESOLVED"
    assert items[5203]["active_event_id"] is None
    assert viewer.get("/api/v1/web/stations/5202").json()["active_event_lifecycle"] == "ACTIVE"
