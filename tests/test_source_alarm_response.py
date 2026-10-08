from datetime import datetime

import pytest

from radmon.lan import LanSource, RemoteMariaDBSource


class SourceFixture:
    """Small MariaDB-shaped fixture for the source response transaction."""

    def __init__(self, *, flag=0, ack=0, i_op=None, readback_flag=None, commit_error=False):
        self.row = [5201, datetime(2026, 10, 8, 12, 34, 56), ack, flag, i_op, None, None]
        self.readback_flag = readback_flag
        self.commit_error = commit_error
        self.sqls = []
        self.update_params = None
        self.committed = False
        self._before_update = list(self.row)

    def cursor(self):
        return SourceCursor(self)

    def commit(self):
        if self.commit_error:
            # Simulate a server-side commit followed by a lost client response.
            self.committed = True
            raise RuntimeError("commit failed")
        self.committed = True

    def rollback(self):
        self.row = list(self._before_update)

    def close(self):
        pass


class SourceCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.db.sqls.append(sql)
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("select"):
            if params[0] != self.db.row[0] or params[1] != self.db.row[1]:
                self.result = None
                return
            row = list(self.db.row)
            if self.db.readback_flag is not None and not normalized.endswith("for update"):
                row[3] = self.db.readback_flag
            self.result = tuple(row)
            return
        if normalized.startswith("update"):
            self.db._before_update = list(self.db.row)
            self.db.update_params = params
            self.db.row[3] = 1
            self.db.row[4] = params[0]
            self.db.row[5] = params[1]
            self.db.row[6] = params[2]
            self.rowcount = 1

    def fetchone(self):
        return self.result


def _remote(db):
    return RemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=lambda: db,
    )


def test_confirmed_response_reads_back_exact_row_and_preserves_ack():
    db = SourceFixture(ack=0)
    remote = _remote(db)

    result = remote.respond_alarm_result(
        5201,
        db.row[1],
        action="Konfirmasi",
        pic="Operator",
        note="Diperiksa",
        at=datetime(2026, 10, 8, 12, 35, 1),
    )

    assert result.status == "CONFIRMED"
    assert result.source_i_flag == 1
    assert result.source_ack == 0
    assert result.source_i_op == datetime(2026, 10, 8, 12, 35, 1)
    assert db.committed is True
    assert db.row[2] == 0
    update = next(sql for sql in db.sqls if sql.lower().lstrip().startswith("update"))
    assert "i_flag = 1" in " ".join(update.lower().split())
    assert "ack =" not in update.lower()
    assert db.update_params[-2:] == (5201, db.row[1])


def test_already_handled_exact_row_is_idempotent_without_second_write():
    handled_at = datetime(2026, 10, 8, 12, 35, 1)
    db = SourceFixture(flag=1, i_op=handled_at)
    remote = _remote(db)

    result = remote.respond_alarm_result(
        5201,
        db.row[1],
        action="Konfirmasi",
        pic="Operator",
        note="Diperiksa",
        at=datetime(2026, 10, 8, 12, 36),
    )

    assert result.status == "ALREADY_HANDLED"
    assert bool(result) is True
    assert result.source_i_op == handled_at
    assert not any(sql.lower().lstrip().startswith("update") for sql in db.sqls)
    assert db.committed is False


def test_readback_mismatch_is_an_error_not_a_success():
    db = SourceFixture(readback_flag=0)
    remote = _remote(db)

    with pytest.raises(RuntimeError, match="read-back"):
        remote.respond_alarm_result(
            5201,
            db.row[1],
            action="Konfirmasi",
            pic="Operator",
            note="Diperiksa",
            at=datetime(2026, 10, 8, 12, 35, 1),
        )

    assert db.committed is True


def test_ambiguous_commit_uses_bounded_exact_readback_without_second_write():
    db = SourceFixture(commit_error=True)
    remote = _remote(db)

    result = remote.respond_alarm_result(
        5201,
        db.row[1],
        action="Konfirmasi",
        pic="Operator",
        note="Diperiksa",
        at=datetime(2026, 10, 8, 12, 35, 1),
    )

    assert result.status == "ALREADY_HANDLED"
    assert db.row[3] == 1
    assert sum(sql.lower().lstrip().startswith("update") for sql in db.sqls) == 1
    assert sum(sql.lower().lstrip().startswith("select") for sql in db.sqls) <= 3


def test_unreachable_source_never_becomes_a_success():
    def unavailable():
        raise ConnectionError("source unreachable")

    remote = RemoteMariaDBSource(
        LanSource("gd52", "192.168.1.52", 3306, "u", "p", "ipradmon"),
        connection_factory=unavailable,
    )
    with pytest.raises(ConnectionError, match="unreachable"):
        remote.respond_alarm_result(
            5201,
            datetime(2026, 10, 8, 12, 34, 56),
            action="Konfirmasi",
            pic="Operator",
            note="Diperiksa",
            at=datetime(2026, 10, 8, 12, 35, 1),
        )


def test_missing_exact_timestamp_does_not_update_another_alarm():
    db = SourceFixture()
    remote = _remote(db)
    missing = datetime(2026, 10, 8, 12, 34, 57)

    result = remote.respond_alarm_result(
        5201,
        missing,
        action="Konfirmasi",
        pic="Operator",
        note="Diperiksa",
        at=datetime(2026, 10, 8, 12, 35, 1),
    )

    assert result.status == "NOT_FOUND"
    assert bool(result) is False
    assert db.row[3] == 0
    assert not any(sql.lower().lstrip().startswith("update") for sql in db.sqls)
