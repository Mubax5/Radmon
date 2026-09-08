import json

from radmon.audit import AuditTrail
from radmon.security import Role, SecurityStore, UserIdentity


class AppLogger:
    def __init__(self):
        self.messages = []

    def record_applog(self, message, at=None):
        self.messages.append(message)


def test_audit_records_actor_target_before_after_and_applog(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    logger = AppLogger()
    audit = AuditTrail(store, logger)
    identity = UserIdentity("operator1", "Operator 1", Role.OPERATOR)

    audit.record(
        "ALARM_ACK",
        identity,
        "alarm",
        "gd52:5201:2026-09-08 14:00:00",
        before={"acknowledged_at": None},
        after={"action": "Confirm to Location", "pic": "Budi"},
        source="gd52",
    )

    with store._connection() as connection:
        row = connection.execute(
            "SELECT username, role, action, target_type, target_id, source, before_json, after_json, success FROM audit_events"
        ).fetchone()
    assert row[:6] == (
        "operator1",
        "Operator",
        "ALARM_ACK",
        "alarm",
        "gd52:5201:2026-09-08 14:00:00",
        "gd52",
    )
    assert json.loads(row[6]) == {"acknowledged_at": None}
    assert json.loads(row[7])["pic"] == "Budi"
    assert row[8] == 1
    assert logger.messages and "ALARM_ACK" in logger.messages[-1]


def test_audit_redacts_sensitive_values(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    audit = AuditTrail(store)
    identity = UserIdentity("admin", "Admin", Role.ADMINISTRATOR)

    audit.record(
        "USER_UPDATE",
        identity,
        "user",
        "x",
        after={
            "password": "secret-pass",
            "pin": "1234",
            "session_token": "token-value",
            "db_password": "db-secret",
            "display_name": "X",
        },
    )

    with store._connection() as connection:
        text = connection.execute("SELECT after_json FROM audit_events").fetchone()[0]
    assert "secret-pass" not in text
    assert "1234" not in text
    assert "token-value" not in text
    assert "db-secret" not in text
    assert "[REDACTED]" in text
    assert "display_name" in text
