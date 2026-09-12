from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_env_uses_verified_production_endpoints_and_archive_settings():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "RADMON_CENTRAL_HOST=192.168.1.2" in text
    assert "RADMON_LAN_SOURCES=server50@192.168.1.50;server52@192.168.1.52;server38@192.168.1.38" in text
    assert "RADMON_LAN_DB_NAME=ipradmon" in text
    assert "RADMON_LAN_POLL_INTERVAL=2" in text
    assert "RADMON_LAN_OFFLINE_AFTER_FAILURES=3" in text
    assert "RADMON_LAN_DB_PASSWORD=\n" in text
    for name in (
        "RADMON_ARCHIVE_ENABLED=1",
        "RADMON_ARCHIVE_DIR=archives",
        "RADMON_ARCHIVE_TIMEZONE=Asia/Jakarta",
        "RADMON_ARCHIVE_MIN_RETENTION_YEARS=5",
        "RADMON_ARCHIVE_CHECK_INTERVAL=60",
    ):
        assert name in text


def test_archive_output_is_not_tracked():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "archives/" in text


def test_readme_documents_safe_quarter_lifecycle_and_direct_reporting():
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "192.168.1.2",
        "app\\radmon.exe",
        "terverifikasi",
        "purge",
        "monthly-recap.csv",
        "manifest.json",
        "5 tahun",
        "tanpa restore",
        "serid production",
    ):
        assert phrase.lower() in text, phrase
