from dataclasses import replace
from pathlib import Path

from radmon.config import Settings
from radmon.paths import ApplicationPaths


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
