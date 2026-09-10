from datetime import datetime, timedelta, timezone

import pytest

from radmon.security import Role, SecurityStore, SecurityError


def test_user_password_and_pin_are_hashed_and_verified(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("admin", "Administrator", Role.ADMINISTRATOR, "SecretPass123!", "2468")

    identity = store.authenticate("admin", "SecretPass123!")
    assert identity is not None
    assert identity.username == "admin"
    assert identity.role is Role.ADMINISTRATOR
    assert store.authenticate("admin", "wrong") is None
    assert store.verify_pin("admin", "2468") is True
    assert store.verify_pin("admin", "0000") is False

    row = store._connection().execute(
        "SELECT password_hash, pin_hash FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    assert row[0] != "SecretPass123!"
    assert row[1] != "2468"
    assert row[0].startswith("pbkdf2_sha256$")
    assert row[1].startswith("pbkdf2_sha256$")


def test_disabled_user_cannot_authenticate_or_verify_pin(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    store.set_user_enabled("op", False)

    assert store.authenticate("op", "Password123!") is None
    assert store.verify_pin("op", "1357") is False


def test_role_permission_matrix(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    assert store.role_allows(Role.ADMINISTRATOR, "manage_users")
    assert store.role_allows(Role.ADMINISTRATOR, "edit_station")
    assert store.role_allows(Role.ADMINISTRATOR, "ack_alarm")
    assert store.role_allows(Role.OPERATOR, "ack_alarm")
    assert not store.role_allows(Role.OPERATOR, "manage_users")
    assert not store.role_allows(Role.OPERATOR, "edit_station")
    assert not store.role_allows(Role.VIEWER, "ack_alarm")
    assert store.role_allows(Role.VIEWER, "view")


def test_session_is_opaque_and_expires(tmp_path):
    now = datetime(2026, 9, 8, 7, 0, tzinfo=timezone.utc)
    store = SecurityStore(tmp_path / "security.db", now=lambda: now)
    store.create_user("viewer", "Viewer", Role.VIEWER, "Password123!", "9999")
    token = store.create_session("viewer", ttl_seconds=60)

    assert token and "viewer" not in token
    assert store.session_user(token).username == "viewer"

    store._now = lambda: now + timedelta(seconds=61)
    assert store.session_user(token) is None


def test_sensitive_permission_requires_role_and_pin(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")

    store.require_sensitive(identity, "ack_alarm", "1357")
    with pytest.raises(SecurityError):
        store.require_sensitive(identity, "manage_users", "1357")
    with pytest.raises(SecurityError):
        store.require_sensitive(identity, "ack_alarm", "0000")
