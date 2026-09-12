from radmon.archive_reports import ArchiveReportRepository
from radmon.archive_store import CentralArchiveStore
from radmon.repository import MariaDBRepository


def test_repository_and_archive_behavior_is_not_monkey_patched():
    assert MariaDBRepository.live_rows.__module__ == "radmon.repository"
    assert CentralArchiveStore.monthly_recap_rows.__module__ == "radmon.archive_store"
    assert ArchiveReportRepository.alarm_history.__module__ == "radmon.archive_reports"
