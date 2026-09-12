from pathlib import Path

from radmon.archive_reports import ArchiveReportRepository
from radmon.archive_store import CentralArchiveStore
from radmon.lan import LanAggregator, MariaCentralStore, RemoteMariaDBSource
from radmon.remote_alarm import RemoteAlarmMirror
from radmon.repository import MariaDBRepository


ROOT = Path(__file__).resolve().parents[1]


def test_repository_and_archive_behavior_is_not_monkey_patched():
    assert MariaDBRepository.live_rows.__module__ == "radmon.repository"
    assert CentralArchiveStore.monthly_recap_rows.__module__ == "radmon.archive_store"
    assert ArchiveReportRepository.alarm_history.__module__ == "radmon.archive_reports"


def test_lan_alarm_behavior_is_defined_in_base_modules():
    assert RemoteMariaDBSource.live_rows.__module__ == "radmon.lan"
    assert LanAggregator.run_live_once.__module__ == "radmon.lan"
    assert MariaCentralStore.mark_alarm_handled.__module__ == "radmon.lan"
    assert RemoteAlarmMirror.mirror.__module__ == "radmon.remote_alarm"
    assert RemoteAlarmMirror.reconcile_source_active_keys.__module__ == "radmon.remote_alarm"


def test_consolidated_revision_files_are_gone():
    for name in (
        "repository_revision.py",
        "archive_store_revision.py",
        "archive_reports_revision.py",
        "lan_revision.py",
        "remote_alarm_revision.py",
        "production_safety_revision.py",
    ):
        assert not (ROOT / "radmon" / name).exists()


def test_one_shot_task7_refactor_artifacts_are_gone():
    assert not (ROOT / "scripts" / "refactor_task7.py").exists()
    assert not (ROOT / "scripts" / "refactor_task7_fixed.py").exists()
    assert not (ROOT / ".github" / "workflows" / "refactor-task7.yml").exists()
    assert not (ROOT / ".github" / "workflows" / "refactor-task7-retry.yml").exists()
    assert not (ROOT / ".github" / "workflows" / "refactor-task7-repair.yml").exists()
