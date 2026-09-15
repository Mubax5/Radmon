from __future__ import annotations

from datetime import datetime, timedelta

from radmon.config import Settings
from radmon.hot_path import RealtimeCentralMariaDBRepository, RealtimeRemoteMariaDBSource
from radmon.lan import LIVE_KEYS, LanSource


def _live_tuple(*, measured_at: datetime, doserate: float, maxidlemin: int = 30, lastmeasec: int = 2):
    values = {
        "serid": 5201,
        "name": "IS-1",
        "location": "Gd.52",
        "warnlevel": 23.0,
        "alarmlevel": 25.0,
        "unit": "µSv/h",
        "audiopath": "",
        "description": "prod",
        "maxidlemin": maxidlemin,
        "dtom": measured_at,
        "doserate": doserate,
        "dose": 0.01,
        "lastrate": doserate,
        "minrate": doserate,
        "maxrate": doserate,
        "avgrate": doserate,
        "lastdose": 0.01,
        "mindose": 0.01,
        "maxdose": 0.01,
        "avgdose": 0.01,
        "lastmea": measured_at,
        "lastmeasec": lastmeasec,
        "meacount": 42,
        "firstmea": measured_at - timedelta(hours=1),
    }
    return tuple(values[key] for key in LIVE_KEYS)


def test_remote_live_hot_path_uses_vrecent_and_targeted_latest_fallback() -> None:
    stale_at = datetime.now() - timedelta(hours=2)
    fresh_at = datetime.now()

    class Cursor:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self._mode = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).lower().split())
            self.statements.append(normalized)
            if "from vrecent" in normalized:
                self._mode = "live"
            elif "from measurement" in normalized and "order by dtom desc limit 1" in normalized:
                self._mode = "latest"
            else:
                self._mode = "other"

        def fetchall(self):
            if self._mode == "live":
                return [_live_tuple(measured_at=stale_at, doserate=0.10)]
            if self._mode == "other":
                return [_live_tuple(measured_at=stale_at, doserate=0.10)]
            return []

        def fetchone(self):
            if self._mode == "latest":
                return (5201, fresh_at, 0.27, 0.02)
            return None

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    connection = Connection()
    remote = RealtimeRemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: connection,
    )

    rows = remote.live_rows()

    assert rows[0]["dtom"] == fresh_at
    assert rows[0]["doserate"] == 0.27
    assert rows[0]["dose"] == 0.02
    assert "from vrecent" in connection.cursor_obj.statements[0]
    assert any(
        "from measurement" in sql
        and "where serid = ?" in sql
        and "order by dtom desc limit 1" in sql
        for sql in connection.cursor_obj.statements[1:]
    )
    assert all("select max(" not in sql for sql in connection.cursor_obj.statements)


def test_remote_live_hot_path_does_not_touch_measurement_when_vrecent_is_fresh() -> None:
    fresh_at = datetime.now()

    class Cursor:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=()):
            self.statements.append(" ".join(str(sql).lower().split()))

        def fetchall(self):
            return [_live_tuple(measured_at=fresh_at, doserate=0.27)]

        def fetchone(self):
            raise AssertionError("fresh vrecent must not trigger a measurement lookup")

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    connection = Connection()
    remote = RealtimeRemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: connection,
    )

    rows = remote.live_rows()

    assert rows[0]["doserate"] == 0.27
    assert len(connection.cursor_obj.statements) == 1
    assert "from vrecent" in connection.cursor_obj.statements[0]
    assert "measurement" not in connection.cursor_obj.statements[0]


def test_central_overview_reads_bounded_recent_table_not_measurement_history() -> None:
    fresh_at = datetime.now()

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
                (5201, "IS-1", "Gd.52", 23.0, 25.0, 30, "µSv/h", fresh_at, 0.27, 0.02, 2, 0)
            ]

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    connection = Connection()
    repository = RealtimeCentralMariaDBRepository(Settings())
    repository._connect = lambda: connection  # type: ignore[method-assign]

    rows = repository.overview_rows()

    assert rows[0]["dtom"] == fresh_at
    assert rows[0]["doserate"] == 0.27
    assert "left join recent" in connection.cursor_obj.sql
    assert "measurement" not in connection.cursor_obj.sql
    assert "select max(" not in connection.cursor_obj.sql
