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


def test_suppress_alarm_permission_matrix(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    assert store.role_allows(Role.ADMINISTRATOR, "suppress_alarm")
    assert store.role_allows(Role.OPERATOR, "suppress_alarm")
    assert not store.role_allows(Role.VIEWER, "suppress_alarm")


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


def test_explicit_wrong_pin_is_rejected_even_with_active_lease(tmp_path):
    store = SecurityStore(tmp_path / "security.db")
    store.create_user("op", "Operator", Role.OPERATOR, "Password123!", "1357")
    identity = store.authenticate("op", "Password123!")
    store.require_sensitive(identity, "ack_alarm", "1357")
    assert store.sensitive_lease_active(identity)
    with pytest.raises(SecurityError, match="PIN"):
        store.require_sensitive(identity, "ack_alarm", "0000")


def test_empty_production_store_imports_legacy_python_users_without_rehash(tmp_path):
    legacy = SecurityStore(tmp_path / "legacy" / "radmon-security.db")
    legacy.create_user("admin", "Administrator", Role.ADMINISTRATOR, "OldPassword123!", "2468")

    production = SecurityStore(tmp_path / "production" / "radmon-security.db")
    assert production.authenticate("admin", "OldPassword123!") is None

    imported = production.import_users_from_database(legacy.path)

    assert imported == 1
    identity = production.authenticate("admin", "OldPassword123!")
    assert identity is not None
    assert identity.role is Role.ADMINISTRATOR
    assert production.verify_pin("admin", "2468") is True


def test_legacy_import_never_merges_into_nonempty_production_store(tmp_path):
    legacy = SecurityStore(tmp_path / "legacy" / "radmon-security.db")
    legacy.create_user("legacy", "Legacy", Role.OPERATOR, "LegacyPass123!", "1357")

    production = SecurityStore(tmp_path / "production" / "radmon-security.db")
    production.create_user("current", "Current", Role.ADMINISTRATOR, "CurrentPass123!", "2468")

    assert production.import_users_from_database(legacy.path) == 0
    assert production.authenticate("legacy", "LegacyPass123!") is None
    assert production.authenticate("current", "CurrentPass123!") is not None
