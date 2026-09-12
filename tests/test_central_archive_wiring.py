from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_managed_central_service_owns_archive_catalog_lifecycle_and_api_wiring():
    source = (ROOT / "radmon" / "central_service.py").read_text(encoding="utf-8")
    assert "ArchiveCatalog" in source
    assert "QuarterArchiveService" in source
    assert "CentralArchiveStore" in source
    assert ".reconcile()" in source
    assert "archive_catalog=archive_catalog" in source
    assert "archive_service=archive_service" in source
    assert "archive_service=archive_service" in source.split("LanRuntime", 2)[-1]


def test_legacy_central_server_only_delegates_to_managed_service():
    source = (ROOT / "central_server.py").read_text(encoding="utf-8")
    assert "from radmon.central_service import CentralService" in source
    assert "ArchiveCatalog" not in source
    assert "LanRuntime" not in source
