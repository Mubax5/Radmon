from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_central_server_owns_archive_catalog_lifecycle_and_api_wiring():
    source = (ROOT / "central_server.py").read_text(encoding="utf-8")
    assert "ArchiveCatalog" in source
    assert "QuarterArchiveService" in source
    assert "CentralArchiveStore" in source
    assert ".reconcile()" in source
    assert "archive_catalog=archive_catalog" in source
    assert "archive_service=archive_service" in source
    assert "archive_service=archive_service" in source.split("LanRuntime", 2)[-1]
