from types import SimpleNamespace

from radmon.runtime_status import RuntimeStatusProjector


def test_projection_schema_is_central_only_sql_contract():
    sql = RuntimeStatusProjector.CREATE_TABLE_SQL.lower()
    assert "create table if not exists radmon_runtime_status" in sql
    assert "policy_state" in sql
    assert "underlying_dose_status" in sql
    assert "suppression_expires_at" in sql


def test_projection_uses_single_upsert_path():
    calls = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()): calls.append((" ".join(sql.split()), params))

    class Connection:
        def cursor(self): return Cursor()
        def commit(self): calls.append(("COMMIT", ()))
        def rollback(self): calls.append(("ROLLBACK", ()))
        def close(self): pass

    settings = SimpleNamespace(
        db_host="central", db_port=3306, db_user="u", db_password="p", db_name="ipradmon"
    )
    projector = RuntimeStatusProjector(settings, connection_factory=lambda: Connection())
    snapshot = {
        "serid": 5201,
        "policy_state": "SUPPRESSED",
        "trigger_count": 0,
        "retrigger_locked": False,
        "suppressed": True,
        "suppression_expires_at": None,
        "suppression_pic": "PIC",
        "suppression_reason": "Calibration",
        "underlying_dose_status": "ALARM",
    }
    projector.project(snapshot)
    projector.project(snapshot)
    upserts = [sql for sql, _ in calls if sql.upper().startswith("INSERT INTO RADMON_RUNTIME_STATUS")]
    assert len(upserts) == 2
    assert all("ON DUPLICATE KEY UPDATE" in sql.upper() for sql in upserts)
    assert not any("REMOTE" in sql.upper() or "192.168.1." in sql for sql, _ in calls)
