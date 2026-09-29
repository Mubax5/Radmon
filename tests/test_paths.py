from dataclasses import replace
from pathlib import Path

from radmon.config import Settings
from radmon.paths import ApplicationPaths
from radmon.secure_services import security_db_path


def test_source_layout_uses_repository_root(tmp_path, monkeypatch):
    monkeypatch.setattr("radmon.paths._source_root", lambda: tmp_path)
    paths = ApplicationPaths.discover(frozen=False)
    assert paths.install_root == tmp_path
    assert paths.app_dir == tmp_path
    assert paths.config_dir == tmp_path
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.archive_dir == tmp_path / "archives"
    assert paths.report_dir == tmp_path / "reports"
    assert paths.asset_path("manuals", "user-manual.html") == tmp_path / "assets" / "manuals" / "user-manual.html"


def test_frozen_layout_keeps_persistent_data_outside_app(tmp_path):
    exe = tmp_path / "app" / "RadMon.exe"
    paths = ApplicationPaths.discover(executable=exe, frozen=True)
    assert paths.app_dir == tmp_path / "app"
    assert paths.install_root == tmp_path
    assert paths.config_dir == tmp_path / "config"
    assert paths.env_file == tmp_path / "config" / ".env"
    assert paths.runtime_dir == tmp_path / "runtime"
    assert paths.archive_dir == tmp_path / "archives"
    assert paths.report_dir == tmp_path / "reports"
    assert paths.assets_dir == tmp_path / "app" / "assets"


def test_settings_resolve_default_persistent_paths_to_application_layout(tmp_path):
    paths = ApplicationPaths.discover(executable=tmp_path / "app" / "RadMon.exe", frozen=True)
    settings = Settings().for_application_paths(paths)
    assert settings.runtime_dir == tmp_path / "runtime"
    assert settings.archive_dir == tmp_path / "archives"
    assert settings.report_dir == tmp_path / "reports"
    assert settings.log_dir == tmp_path / "runtime" / "logs"


def test_settings_preserve_explicit_absolute_paths(tmp_path):
    paths = ApplicationPaths.discover(executable=tmp_path / "app" / "RadMon.exe", frozen=True)
    custom = tmp_path / "custom-runtime"
    settings = replace(Settings(), runtime_dir=custom).for_application_paths(paths)
    assert settings.runtime_dir == custom


def test_central_and_admin_security_store_path_is_cwd_independent_source_and_frozen(tmp_path, monkeypatch):
    source_root = tmp_path / "source-install"
    frozen_root = tmp_path / "frozen-install"
    cwd_a = tmp_path / "cwd-a"
    cwd_b = tmp_path / "cwd-b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    monkeypatch.setenv("RADMON_SECURITY_DB", "runtime/radmon-security.db")

    monkeypatch.setattr("radmon.paths._source_root", lambda: source_root)
    source_paths = ApplicationPaths.discover(frozen=False)
    monkeypatch.chdir(cwd_a)
    source_settings = Settings.from_env(env_file=None).for_application_paths(source_paths)
    source_path = security_db_path(source_settings)
    monkeypatch.chdir(cwd_b)
    assert security_db_path(source_settings) == source_path

    frozen_paths = ApplicationPaths.discover(executable=frozen_root / "app" / "RadMon Admin.exe", frozen=True)
    monkeypatch.chdir(cwd_a)
    admin_settings = Settings.from_env(env_file=None).for_application_paths(frozen_paths)
    admin_path = security_db_path(admin_settings)
    monkeypatch.chdir(cwd_b)
    central_settings = Settings.from_env(env_file=None).for_application_paths(
        ApplicationPaths.discover(executable=frozen_root / "app" / "RadMon.exe", frozen=True)
    )
    assert security_db_path(central_settings) == admin_path
    assert admin_path == frozen_root / "runtime" / "radmon-security.db"
    assert source_path == source_root / "runtime" / "radmon-security.db"


def test_security_store_migrates_single_legacy_cwd_database_non_destructively(tmp_path, monkeypatch):
    import sqlite3

    from radmon.secure_services import security_db_path

    root = tmp_path / "install"
    old_cwd = tmp_path / "old-cwd"
    legacy = old_cwd / "runtime" / "radmon-security.db"
    legacy.parent.mkdir(parents=True)
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE preserved (value TEXT)")
        connection.execute("INSERT INTO preserved VALUES ('audit-and-auth-state')")
    paths = ApplicationPaths.discover(executable=root / "app" / "RadMon.exe", frozen=True)
    monkeypatch.setenv("RADMON_SECURITY_DB", "runtime/radmon-security.db")
    settings = Settings.from_env(env_file=None).for_application_paths(paths)
    monkeypatch.chdir(old_cwd)

    target = security_db_path(settings)
    assert target == root / "runtime" / "radmon-security.db"
    assert legacy.is_file()
    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM preserved").fetchone()[0] == "audit-and-auth-state"


def test_security_store_refuses_ambiguous_legacy_databases(tmp_path, monkeypatch):
    import sqlite3
    import pytest

    from radmon.secure_services import security_db_path

    root = tmp_path / "install"
    old_cwd = tmp_path / "old-cwd"
    (old_cwd / "runtime").mkdir(parents=True)
    (root / "app" / "runtime").mkdir(parents=True)
    for database in (old_cwd / "runtime" / "radmon-security.db", root / "app" / "runtime" / "radmon-security.db"):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE retained (value TEXT)")
            connection.execute("INSERT INTO retained VALUES ('data')")
    paths = ApplicationPaths.discover(executable=root / "app" / "RadMon.exe", frozen=True)
    monkeypatch.setenv("RADMON_SECURITY_DB", "runtime/radmon-security.db")
    monkeypatch.chdir(old_cwd)
    settings = Settings.from_env(env_file=None).for_application_paths(paths)

    with pytest.raises(RuntimeError, match="Multiple legacy RadMon security databases"):
        security_db_path(settings)
