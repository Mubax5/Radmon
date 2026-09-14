from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_auto_updater_is_packaged_and_registered():
    installer = (ROOT / "packaging/RadMon.iss").read_text(encoding="utf-8")
    install_helper = ROOT / "packaging/install_updater.ps1"
    updater = ROOT / "packaging/radmon_update.ps1"

    assert install_helper.exists(), "installer needs a helper that registers the updater task"
    assert updater.exists(), "installer needs the persistent updater script"
    assert 'Source: "packaging\\radmon_update.ps1"' in installer
    assert 'Source: "packaging\\install_updater.ps1"' in installer
    assert "RadMon Updater" in installer


def test_updater_defaults_on_but_supports_explicit_disable():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    updater = (ROOT / "packaging/radmon_update.ps1").read_text(encoding="utf-8")

    assert "RADMON_AUTO_UPDATE=1" in env_example
    assert "RADMON_AUTO_UPDATE" in updater
    for disabled in ("0", "false", "no", "off", "disabled"):
        assert disabled in updater.lower()


def test_updater_refuses_downgrade_and_verifies_before_installing():
    script = (ROOT / "packaging/radmon_update.ps1").read_text(encoding="utf-8")

    assert "Compare-ReleaseAncestry" in script
    assert "behind" in script.lower()
    assert "diverged" in script.lower()
    assert "Get-FileHash" in script
    assert "RadMon-Setup.exe.sha256" in script
    assert "Start-Process" in script
    assert script.index("Get-FileHash") < script.index("Start-Process")


def test_updater_uses_latest_release_and_installed_release_marker():
    script = (ROOT / "packaging/radmon_update.ps1").read_text(encoding="utf-8")

    assert "refs/tags/latest" in script
    assert "releases/download/latest/RadMon-Setup.exe" in script
    assert "app\\release.json" in script or "app/release.json" in script
    assert "Global\\RadMonAutoUpdater" in script
    assert "radmon-updater.log" in script


def test_windows_build_embeds_release_sha_and_smokes_updater():
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")

    assert "release.json" in workflow
    assert "$env:GITHUB_SHA" in workflow
    assert "Smoke test updater helper" in workflow
    assert 'Get-ScheduledTask -TaskName "RadMon Updater"' in workflow
