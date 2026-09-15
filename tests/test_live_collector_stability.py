from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.central_api import CentralMariaDBRepository
from radmon.config import Settings
from radmon.lan import LanAggregator, LanCheckpointStore, LanSource, RemoteMariaDBSource
from radmon.lan_store import BatchedMariaCentralStore
from radmon.security import Role, SecurityStore
from radmon.secure_api import SESSION_COOKIE
from radmon.web_api import attach_web_api_routes


def test_remote_live_rows_reads_authoritative_latest_measurement_not_only_vrecent() -> None:
    fresh_at = datetime(2026, 9, 15, 6, 30, 0)

    class Cursor:
        def __init__(self) -> None:
            self.sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self.sql = " ".join(str(sql).lower().split())

        def fetchall(self):
            return [
                (
                    5201,
                    "IS-1",
                    "Gd.52",
                    23.0,
                    25.0,
                    "µSv/h",
                    "",
                    "prod",
                    30,
                    fresh_at,
                    0.27,
                    0.01,
                    0.26,
                    0.10,
                    0.30,
                    0.20,
                    0.01,
                    0.0,
                    0.02,
                    0.01,
                    fresh_at,
                    2,
                    42,
                    datetime(2026, 9, 15, 6, 0, 0),
                )
            ]

    class Connection:
        def __init__(self) -> None:
            self.c = Cursor()

        def cursor(self):
            return self.c

        def close(self):
            pass

    connection = Connection()
    remote = RemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: connection,
    )

    rows = remote.live_rows()

    assert rows[0]["dtom"] == fresh_at
    assert rows[0]["doserate"] == 0.27
    assert "from device" in connection.c.sql
    assert "from measurement" in connection.c.sql
    assert "select max(" in connection.c.sql
    assert ".dtom)" in connection.c.sql


def test_central_overview_snapshot_reads_bounded_vrecent_with_one_connection() -> None:
    fresh_at = datetime(2026, 9, 15, 6, 30, 0)

    class Cursor:
        def __init__(self) -> None:
            self.sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self.sql = " ".join(str(sql).lower().split())

        def fetchall(self):
            return [
                (5201, "IS-1", "Gd.52", 23.0, 25.0, 30, "µSv/h", fresh_at, 0.27, 0.01, 2, 0)
            ]

    class Connection:
        def __init__(self) -> None:
            self.c = Cursor()
            self.closed = 0

        def cursor(self):
            return self.c

        def close(self):
            self.closed += 1

    connection = Connection()
    repository = CentralMariaDBRepository(Settings())
    calls = 0

    def connect():
        nonlocal calls
        calls += 1
        return connection

    repository._connect = connect  # type: ignore[method-assign]

    rows = repository.overview_rows()

    assert calls == 1
    assert connection.closed == 1
    assert rows[0]["serid"] == 5201
    assert rows[0]["dtom"] == fresh_at
    assert rows[0]["doserate"] == 0.27
    assert "from vrecent" in connection.c.sql
    assert "from measurement" not in connection.c.sql
    assert "max(dtom)" in connection.c.sql


def test_web_overview_uses_batched_snapshot_instead_of_n_plus_one_latest_queries(tmp_path) -> None:
    fresh_at = datetime.now()

    class Repository:
        def overview_rows(self):
            return [
                {
                    "serid": 5201,
                    "name": "IS-1",
                    "location": "Gd.52",
                    "warnlevel": 23.0,
                    "alarmlevel": 25.0,
                    "maxidlemin": 30,
                    "unit": "µSv/h",
                    "dtom": fresh_at,
                    "doserate": 0.27,
                    "dose": 0.01,
                    "previnterval": 2,
                    "stat": 0,
                }
            ]

        def stations(self):
            raise AssertionError("overview must not open a stations query")

        def latest(self, serid: int):
            raise AssertionError("overview must not open one latest query per station")

        def history(self, serid: int, limit: int = 240):
            return []

    security = SecurityStore(tmp_path / "security.db")
    security.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "2468")
    token = security.create_session("viewer", 3600)
    app = FastAPI()
    attach_web_api_routes(app, security=security, repository=Repository())
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/api/v1/web/overview")

    assert response.status_code == 200
    assert response.json()["counts"] == {"normal": 1, "warning": 0, "alarm": 0, "offline": 0}


def test_alarm_policy_live_cycle_reads_source_live_snapshot_only_once(tmp_path) -> None:
    class CountingRemote:
        def __init__(self) -> None:
            self.live_calls = 0

        def live_rows(self):
            self.live_calls += 1
            return [
                {
                    "serid": 5201,
                    "name": "IS-1",
                    "location": "Gd.52",
                    "warnlevel": 23.0,
                    "alarmlevel": 25.0,
                    "maxidlemin": 30,
                    "unit": "µSv/h",
                    "description": "prod",
                    "audiopath": "",
                    "dtom": datetime(2026, 9, 15, 6, 30, 0),
                    "doserate": 0.27,
                    "dose": 0.01,
                    "lastrate": 0.26,
                    "minrate": 0.10,
                    "maxrate": 0.30,
                    "avgrate": 0.20,
                    "lastdose": 0.01,
                    "mindose": 0.0,
                    "maxdose": 0.02,
                    "avgdose": 0.01,
                    "firstmea": datetime(2026, 9, 15, 6, 0, 0),
                    "lastmea": datetime(2026, 9, 15, 6, 30, 0),
                    "lastmeasec": 2,
                    "meacount": 42,
                }
            ]

        def alarms_after(self, checkpoint, limit=500):
            return []

    class Central:
        def upsert_live_rows(self, source_id, rows):
            return len(list(rows))

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            return []

    class FakeSecurity:
        def _connection(self):
            return FakeDb()

    class PolicyStore:
        security = FakeSecurity()

        def pending_source_silences(self, source_id, at=None, limit=25):
            return []

    class Policy:
        store = PolicyStore()

        def process_cycle(self, source_id, live_rows, alarm_rows):
            assert len(live_rows) == 1

        @staticmethod
        def now():
            return datetime.now()

    security = SecurityStore(tmp_path / "security-sidecar.db")
    checkpoints = LanCheckpointStore(security)
    source = LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon")
    remote = CountingRemote()
    aggregator = LanAggregator(Central(), checkpoints, remote_factory=lambda value: remote)
    aggregator.alarm_policy = Policy()

    result = aggregator.run_live_once(source)

    assert result.error is None
    assert remote.live_calls == 1


def test_central_live_upsert_uses_one_connection_with_history_then_rolling_commits() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.rowcount = 1
            self._selected = None
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).lower().split())
            self.statements.append(normalized)
            if normalized.startswith("select name, location, hwaddress, hwtype from device"):
                self._selected = None

        def fetchone(self):
            return self._selected

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()
            self.commits = 0
            self.rollbacks = 0
            self.closed = 0

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closed += 1

    connections: list[Connection] = []

    def connect():
        connection = Connection()
        connections.append(connection)
        return connection

    store = BatchedMariaCentralStore(Settings(), connection_factory=connect)
    rows = [
        {
            "serid": serid,
            "name": f"Station {serid}",
            "location": "Gd.52",
            "warnlevel": 23.0,
            "alarmlevel": 25.0,
            "maxidlemin": 30,
            "unit": "µSv/h",
            "description": "prod",
            "dtom": datetime(2026, 9, 15, 6, 30, offset),
            "doserate": 0.20 + offset / 100,
            "dose": 0.01,
            "lastrate": 0.19,
            "minrate": 0.10,
            "maxrate": 0.30,
            "avgrate": 0.20,
            "lastdose": 0.01,
            "mindose": 0.0,
            "maxdose": 0.02,
            "avgdose": 0.01,
            "firstmea": datetime(2026, 9, 15, 6, 0, 0),
            "lastmea": datetime(2026, 9, 15, 6, 30, offset),
            "lastmeasec": 2,
            "meacount": 42,
        }
        for serid, offset in ((5201, 0), (5202, 2))
    ]

    changed = store.upsert_live_rows("gd52", rows)

    assert changed == 2
    assert len(connections) == 1
    assert connections[0].commits == 2
    assert connections[0].rollbacks == 0
    assert connections[0].closed == 1
    statements = connections[0].cursor_obj.statements
    assert sum("insert into device" in sql for sql in statements) == 2
    assert sum("insert ignore into recent" in sql for sql in statements) == 2
    assert sum("insert ignore into measurement" in sql for sql in statements) == 2
    assert sum("delete from recent" in sql for sql in statements) <= 1
