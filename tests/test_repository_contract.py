from __future__ import annotations
from datetime import datetime
from radmon.config import Settings
from radmon.models import Measurement
from radmon.repository import MariaDBRepository, make_sample_key


class FakeCursor:
    def __init__(self, executed): self.executed=executed; self.lastrowid=77; self._fetchone=None; self._fetchall=[]
    def execute(self, sql, params=()): self.executed.append((" ".join(sql.split()), tuple(params))); return self
    def fetchone(self): return self._fetchone
    def fetchall(self): return self._fetchall
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False


class FakeConnection:
    def __init__(self): self.executed=[]; self.commits=0; self.rollbacks=0; self.closed=False
    def cursor(self): return FakeCursor(self.executed)
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): self.closed = True


def test_insert_measurement_writes_raw_measurement_and_sync_queue_atomically():
    connection=FakeConnection(); repo=MariaDBRepository(Settings(), connection_factory=lambda: connection); measurement=Measurement(5202, datetime(2026,9,7,10,0,0), 0.123, 2, 0)
    repo.insert_measurement(measurement, raw="0.12300", queue_sync=True)
    sql_text="\n".join(sql for sql,_ in connection.executed)
    assert "INSERT INTO rawdata" in sql_text and "INSERT INTO measurement" in sql_text and "INSERT IGNORE INTO radmon_sync_queue" in sql_text
    measurement_params=next(params for sql,params in connection.executed if "INSERT INTO measurement" in sql)
    assert measurement_params == (5202, datetime(2026,9,7,10,0,0), 0.123, 2, 0)
    assert connection.commits==1 and connection.rollbacks==0 and connection.closed is True


def test_sample_key_is_stable_and_changes_when_measurement_changes():
    one=Measurement(5202,datetime(2026,9,7,10,0,0),0.123,2,0); two=Measurement(5202,datetime(2026,9,7,10,0,2),0.123,2,0)
    assert make_sample_key(one)==make_sample_key(one); assert make_sample_key(one)!=make_sample_key(two); assert len(make_sample_key(one))==64


def test_schema_extension_is_additive_and_contains_alarm_sync_tables():
    source=open("database/schema_extension.sql",encoding="utf-8").read().lower()
    for table in ("radmon_alarm_event","radmon_sync_queue","radmon_sync_receipt"): assert f"create table if not exists `{table}`" in source
    assert "drop table" not in source and "drop database" not in source


def test_demo_registration_targets_5202_is1_koridor():
    source=open("scripts/register_demo_station.py",encoding="utf-8").read()
    assert "5202" in source and "IS-1 Koridor" in source and "Gd.52" in source and "warnlevel" in source and "alarmlevel" in source
