from datetime import datetime

import pytest

from radmon.lan import LanAggregator, LanCheckpointStore, LanSource, MariaCentralStore
from radmon.security import SecurityStore


class DrainRemote:
    def __init__(self, source):
        self.source = source
        self.rows = [
            {"serid": 5201, "dtom": datetime(2026, 9, 30, 23, 59, 56), "doserate": 1.0, "dose": 0.01, "previnterval": 2, "stat": 0},
            {"serid": 5201, "dtom": datetime(2026, 9, 30, 23, 59, 58), "doserate": 1.1, "dose": 0.02, "previnterval": 2, "stat": 0},
            {"serid": 5201, "dtom": datetime(2026, 10, 1, 0, 0, 0), "doserate": 1.2, "dose": 0.03, "previnterval": 2, "stat": 0},
        ]

    def devices(self):
        return [{"serid": 5201, "name": "IS-1", "location": "Gd.52", "warnlevel": 23,
                 "alarmlevel": 25, "maxidlemin": 30, "unit": "µSv/h", "description": "prod"}]

    def latest_measurement_at_or_before(self, serid, cutoff):
        values = [row["dtom"] for row in self.rows if row["dtom"] < cutoff]
        return max(values) if values else None

    def measurements_after(self, serid, after, limit):
        return [row for row in self.rows if after is None or row["dtom"] > after][:limit]


class DrainCentral:
    def __init__(self):
        self.rows = []

    def ensure_remote_device(self, source_id, row):
        pass

    def import_measurements(self, source_id, rows):
        self.rows.extend(rows)
        return len(rows)


def test_drain_source_stops_at_old_quarter_cutoff_and_persists_remote_checkpoint(tmp_path):
    security = SecurityStore(tmp_path / "security.db")
    checkpoints = LanCheckpointStore(security)
    source = LanSource("gd52", "db", 3306, "u", "p", "ipradmon")
    central = DrainCentral()
    aggregator = LanAggregator(central, checkpoints, remote_factory=DrainRemote, batch_size=10)
    drained = aggregator.drain_source_until(source, datetime(2026, 10, 1, 0, 0, 0))
    assert drained[5201] == datetime(2026, 9, 30, 23, 59, 58)
    assert checkpoints.load("gd52", 5201) == datetime(2026, 9, 30, 23, 59, 58)
    assert [row["dtom"] for row in central.rows] == [
        datetime(2026, 9, 30, 23, 59, 56),
        datetime(2026, 9, 30, 23, 59, 58),
    ]


class IdentityCursor:
    def __init__(self):
        self.rowcount = 1
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return ("Other", "Gd.50", "gd50", "remote")


class IdentityConnection:
    def __init__(self):
        self.cursor_obj = IdentityCursor()

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_same_serid_from_different_source_is_not_silently_merged(monkeypatch):
    monkeypatch.delenv("RADMON_SHARED_SERIDS", raising=False)
    connection = IdentityConnection()
    store = MariaCentralStore(object(), connection_factory=lambda: connection)
    with pytest.raises(RuntimeError, match="SERID conflict"):
        store.ensure_remote_device("gd52", {
            "serid": 5201, "name": "IS-1", "location": "Gd.52", "warnlevel": 23,
            "alarmlevel": 25, "maxidlemin": 30, "unit": "µSv/h", "description": "prod",
        })
