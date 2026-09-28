"""RED test for offline fallback: offline stations must show last known dose no matter age.

Covers production issue:
- SERID 5701 last measurement 2026-06-23 must show dose + diperbarui, status offline
- Gd.50 3000-3004 (e.g., 3004 R. Insenerasi) same
- Web Perhatian table currently shows "—" and "Belum ada measurement live"

Contract:
- dose_rate and dtom must NEVER be hidden when historical measurement exists
- status must be offline with appropriate offline_reason when stale or null vrecent
- Grafana and web must use same fallback rule (measurement fallback)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.security import Role, SecurityStore
from radmon.web_api import attach_web_api_routes, _station_status
from radmon.secure_api import SESSION_COOKIE


class FakeRepoWithHistoricalFallback:
    """Simulates central repo where vrecent/recent is empty but measurement has old data.

    Before fix, overview_rows returns dtom=None, latest returns None.
    After fix, both should return historical measurement.
    """
    def stations(self):
        return [
            {"serid": 5701, "name": "IS-2", "location": "Gd.57", "description": "detektor 5701", "warnlevel": 23.0, "alarmlevel": 25.0, "maxidlemin": 30, "unit": "µSv/h"},
            {"serid": 3004, "name": "R. Insenerasi", "location": "Gd.50", "description": "incineration", "warnlevel": 8.0, "alarmlevel": 10.0, "maxidlemin": 30, "unit": "µSv/h"},
            {"serid": 3000, "name": "R. Resin Penukar Ion", "location": "Gd.50", "description": "resin", "warnlevel": 100.0, "alarmlevel": 150.0, "maxidlemin": 30, "unit": "µSv/h"},
        ]

    def overview_rows(self):
        # Simulate buggy current SQL: LEFT JOIN recent/vrecent gives null when no recent row
        # even though measurement exists. This is what production shows for offline old stations.
        return [
            {"serid": 5701, "name": "IS-2", "location": "Gd.57", "description": "detektor 5701", "warnlevel": 23.0, "alarmlevel": 25.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": None, "doserate": None, "dose": None, "previnterval": None, "stat": None},
            {"serid": 3004, "name": "R. Insenerasi", "location": "Gd.50", "description": "incineration", "warnlevel": 8.0, "alarmlevel": 10.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": None, "doserate": None, "dose": None, "previnterval": None, "stat": None},
            {"serid": 3000, "name": "R. Resin Penukar Ion", "location": "Gd.50", "description": "resin", "warnlevel": 100.0, "alarmlevel": 150.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": None, "doserate": None, "dose": None, "previnterval": None, "stat": None},
        ]

    def latest(self, serid: int):
        return None

    def history(self, serid: int, limit: int = 240):
        # Historical measurement exists even >1 year old
        old = datetime(2026, 6, 23, 10, 0, 0)
        if serid == 5701:
            return [{"serid": 5701, "dtom": old, "doserate": 0.17, "dose": 0.001, "previnterval": 2, "stat": 0}]
        if serid == 3004:
            # simulate stale 15 Sep
            return [{"serid": 3004, "dtom": datetime(2025, 9, 15, 8, 0, 0), "doserate": 0.22, "dose": 0.002, "previnterval": 2, "stat": 0}]
        if serid == 3000:
            return [{"serid": 3000, "dtom": datetime(2025, 1, 10, 12, 0, 0), "doserate": 0.31, "dose": 0.003, "previnterval": 2, "stat": 0}]
        return []


class FakeRepoWithRealFallback:
    """Represents FIXED repo: overview_rows already falls back to measurement."""
    def stations(self):
        return FakeRepoWithHistoricalFallback().stations()

    def overview_rows(self):
        # After fix, overview_rows COALESCES to measurement
        return [
            {"serid": 5701, "name": "IS-2", "location": "Gd.57", "description": "detektor 5701", "warnlevel": 23.0, "alarmlevel": 25.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": datetime(2026, 6, 23, 10, 0, 0), "doserate": 0.17, "dose": 0.001, "previnterval": 2, "stat": 0},
            {"serid": 3004, "name": "R. Insenerasi", "location": "Gd.50", "description": "incineration", "warnlevel": 8.0, "alarmlevel": 10.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": datetime(2025, 9, 15, 8, 0, 0), "doserate": 0.22, "dose": 0.002, "previnterval": 2, "stat": 0},
            {"serid": 3000, "name": "R. Resin Penukar Ion", "location": "Gd.50", "description": "resin", "warnlevel": 100.0, "alarmlevel": 150.0, "maxidlemin": 30, "unit": "µSv/h", "dtom": datetime(2025, 1, 10, 12, 0, 0), "doserate": 0.31, "dose": 0.003, "previnterval": 2, "stat": 0},
        ]

    def latest(self, serid: int):
        mapping = {row["serid"]: row for row in self.overview_rows()}
        return mapping.get(serid)

    def history(self, serid: int, limit: int = 240):
        return FakeRepoWithHistoricalFallback().history(serid, limit)


def make_client(tmp_path, repo):
    security = SecurityStore(tmp_path / "db.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "1234")
    token = security.create_session("viewer", 3600)
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=repo)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    return client


def test_offline_station_shows_last_known_dose_not_dash(tmp_path):
    """RED: 5701 and 3004 must show dose even though vrecent null / stale 1 year+.

    Before fix, overview returns doserate None and dtom None -> UI shows "—" and
    "Belum ada measurement live". After fix, both fields must be populated and
    status must remain offline.
    """
    client = make_client(tmp_path, FakeRepoWithRealFallback())
    resp = client.get("/api/v1/web/overview")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {s["serid"]: s for s in body["stations"]}

    # 5701: offline but must show last known
    s5701 = by_id[5701]
    assert s5701["status"] == "offline", "offline station must stay offline"
    assert s5701["doserate"] is not None, "must not hide dose for offline 5701"
    assert s5701["doserate"] == 0.17
    assert s5701["dtom"] is not None, "diperbarui must show historical timestamp"
    assert "2026-06-23" in s5701["dtom"]
    assert s5701["offline_reason"] is not None
    # dose must not be hidden, offline_reason must explain idle, not "Belum ada measurement"
    assert s5701["offline_reason"] != "Belum ada measurement dari perangkat"
    assert "Mea" in s5701["offline_reason"] or "idle" in s5701["offline_reason"].lower()

    # 3004 R. Insenerasi (Gd.50) also
    s3004 = by_id[3004]
    assert s3004["status"] == "offline"
    assert s3004["doserate"] == 0.22
    assert s3004["dtom"] is not None
    assert s3004["offline_reason"] != "Belum ada measurement dari perangkat"

    # Also direct station_detail must fallback
    detail = client.get("/api/v1/web/stations/5701")
    assert detail.status_code == 200
    assert detail.json()["doserate"] == 0.17
    assert detail.json()["dtom"] is not None


def test_buggy_repo_currently_hides_dose_red(tmp_path):
    """This test documents the BUG: with current buggy repo, dose is hidden.

    After fix, the app layer must fallback to history so even buggy overview_rows
    (with null dtom) still shows dose via measurement fallback. This test will
    FAIL before fix and PASS after fix, proving the fallback logic is in the
    web layer (not just SQL).
    """
    buggy = FakeRepoWithHistoricalFallback()
    client = make_client(tmp_path, buggy)
    resp = client.get("/api/v1/web/overview")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {s["serid"]: s for s in body["stations"]}
    # After fix, even though overview_rows is null, web layer should have fallen
    # back to history and thus show dose.
    for serid in (5701, 3004, 3000):
        station = by_id[serid]
        assert station["doserate"] is not None, f"fallback must provide dose for {serid}, got None (bug: shows dash)"
        assert station["dtom"] is not None, f"fallback must provide diperbarui for {serid}"
        assert station["status"] == "offline"

    # The tabular station list and direct detail route use the same fallback.
    listed = client.get("/api/v1/web/stations")
    assert listed.status_code == 200
    assert {row["serid"]: row for row in listed.json()}[3004]["doserate"] == 0.22
    detail = client.get("/api/v1/web/stations/3000")
    assert detail.status_code == 200
    assert detail.json()["doserate"] == 0.31
    assert detail.json()["status"] == "offline"


def test_station_status_preserves_dose_when_stale():
    """Unit: stale measurement must keep dose, not hide it."""
    station = {"serid": 5701, "maxidlemin": 30, "warnlevel": 23, "alarmlevel": 25, "name": "IS-2", "location": "Gd.57", "description": "d", "unit": "µSv/h"}
    old = datetime.now() - timedelta(days=90)  # far beyond idle
    row = {"serid": 5701, "dtom": old, "doserate": 0.17, "dose": 0.001, "previnterval": 2, "stat": 0}
    status, dose, dtom, reason = _station_status(station, row)
    assert status == "offline"
    assert dose == 0.17
    assert dtom == old
    assert reason is not None
    # Even 1 year old
    year_old = datetime.now() - timedelta(days=400)
    row2 = {"serid": 5701, "dtom": year_old, "doserate": 0.99, "dose": 0.01, "previnterval": 2, "stat": 0}
    status2, dose2, _, _ = _station_status(station, row2)
    assert status2 == "offline"
    assert dose2 == 0.99


def test_central_latest_fallback_to_measurement(tmp_path):
    """Central latest() must fallback to measurement when vrecent empty."""
    from radmon.central_api import CentralMariaDBRepository
    from radmon.config import Settings

    # Fake connection that returns empty for vrecent but has measurement row
    class Cur:
        def __init__(self, conn):
            self.conn = conn
            self._last_sql = ""
            self._params = ()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=()):
            self._last_sql = " ".join(sql.split())
            self._params = params
        def fetchone(self):
            if "FROM vrecent" in self._last_sql:
                return None
            if "FROM measurement" in self._last_sql:
                # Return measurement fallback for 5701
                if self._params and int(self._params[0]) == 5701:
                    return (5701, datetime(2026, 6, 23, 10, 0, 0), 0.17, 0.001, 2, 0)
                return None
            return None
        def fetchall(self):
            return []

    class Conn:
        def cursor(self): return Cur(self)
        def close(self): pass
        def commit(self): pass
        def rollback(self): pass

    repo = CentralMariaDBRepository(Settings())
    repo._connect = lambda: Conn()
    row = repo.latest(5701)
    assert row is not None, "latest must fallback to measurement when vrecent empty"
    assert row["doserate"] == 0.17
    assert row["dtom"] == datetime(2026, 6, 23, 10, 0, 0)


def test_vrecent_view_definition_includes_measurement_fallback():
    """Grafana and web must share same fallback rule via vrecent view."""
    import inspect
    from radmon.recent_read_model import RollingRecentManager
    src = inspect.getsource(RollingRecentManager._create_view)
    # The view must expose historical last-known values, with lookup bounded to
    # the station's measurement index rather than grouping/scanning all history.
    assert "measurement" in src.lower(), "vrecent view must fallback to measurement for last-known"
    assert "ORDER BY m2.dtom DESC LIMIT 1" in src
    assert "WHERE m2.serid = d2.serid" in src
    assert "FROM measurement GROUP BY" not in src
    assert "MAX(dtom) AS mdtom FROM measurement" not in src
