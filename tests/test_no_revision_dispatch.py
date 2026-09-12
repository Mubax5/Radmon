from pathlib import Path

from radmon.archive_reports import ArchiveReportRepository
from radmon.archive_store import CentralArchiveStore
from radmon.repository import MariaDBRepository


ROOT = Path(__file__).resolve().parents[1]


def test_repository_and_archive_behavior_is_not_monkey_patched():
    assert MariaDBRepository.live_rows.__module__ == "radmon.repository"
    assert CentralArchiveStore.monthly_recap_rows.__module__ == "radmon.archive_store"
    assert ArchiveReportRepository.alarm_history.__module__ == "radmon.archive_reports"


def test_consolidated_repository_archive_revision_files_are_gone():
    for name in (
        "repository_revision.py",
        "archive_store_revision.py",
        "archive_reports_revision.py",
    ):
        assert not (ROOT / "radmon" / name).exists()
