from pathlib import Path

import radmon.production_app as production_app
from radmon.paths import ApplicationPaths


def _paths(root: Path) -> ApplicationPaths:
    return ApplicationPaths(
        install_root=root,
        app_dir=root / "app",
        config_dir=root / "config",
        runtime_dir=root / "runtime",
        archive_dir=root / "archives",
        report_dir=root / "reports",
        log_dir=root / "runtime" / "logs",
        assets_dir=root / "app" / "assets",
        grafana_dir=root / "app" / "grafana",
    )


def test_legacy_root_env_is_copied_to_external_config_once(tmp_path):
    migrate = getattr(production_app, "_migrate_legacy_env", None)
    assert callable(migrate)

    paths = _paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    legacy = tmp_path / ".env"
    legacy.write_text("RADMON_CENTRAL_HOST=192.168.1.2\n", encoding="utf-8")

    assert migrate(paths) is True
    assert paths.env_file.read_text(encoding="utf-8") == legacy.read_text(encoding="utf-8")
    assert legacy.exists()


def test_existing_external_env_is_never_overwritten(tmp_path):
    migrate = getattr(production_app, "_migrate_legacy_env", None)
    assert callable(migrate)

    paths = _paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    legacy = tmp_path / ".env"
    legacy.write_text("RADMON_LAN_SOURCES=legacy\n", encoding="utf-8")
    paths.env_file.write_text("RADMON_LAN_SOURCES=current\n", encoding="utf-8")

    assert migrate(paths) is False
    assert paths.env_file.read_text(encoding="utf-8") == "RADMON_LAN_SOURCES=current\n"
    assert legacy.read_text(encoding="utf-8") == "RADMON_LAN_SOURCES=legacy\n"


def test_source_layout_where_env_paths_are_identical_is_a_noop(tmp_path):
    migrate = getattr(production_app, "_migrate_legacy_env", None)
    assert callable(migrate)

    paths = ApplicationPaths(
        install_root=tmp_path,
        app_dir=tmp_path,
        config_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        archive_dir=tmp_path / "archives",
        report_dir=tmp_path / "reports",
        log_dir=tmp_path / "logs",
        assets_dir=tmp_path / "assets",
        grafana_dir=tmp_path / "grafana",
    )
    paths.env_file.write_text("RADMON_DB_HOST=localhost\n", encoding="utf-8")

    assert migrate(paths) is False
    assert paths.env_file.read_text(encoding="utf-8") == "RADMON_DB_HOST=localhost\n"
