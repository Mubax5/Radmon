# Canonical ownership gate: no runtime monkey-patch layer is allowed back in.
from pathlib import Path

import radmon.grafana_tv as grafana_tv
from radmon.admin.alarm_page import AlarmPage
from radmon.admin.alarm_response_dialog import AlarmResponseDialog
from radmon.admin.auth_dialogs import PinDialog
from radmon.admin.main_window import MainWindow
from radmon.admin.station_admin_dialog import StationAdminDialog
from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.archive_reports import ArchiveReportRepository
from radmon.archive_store import CentralArchiveStore
from radmon.device_admin import DeviceAdminService
from radmon.grafana_bootstrap import GrafanaBootstrap
from radmon.lan import LanAggregator, MariaCentralStore, RemoteMariaDBSource
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.repository import MariaDBRepository
from radmon.security import SecurityStore


ROOT = Path(__file__).resolve().parents[1]


def test_repository_and_archive_behavior_is_not_monkey_patched():
    assert MariaDBRepository.live_rows.__module__ == "radmon.repository"
    assert CentralArchiveStore.monthly_recap_rows.__module__ == "radmon.archive_store"
    assert ArchiveReportRepository.alarm_history.__module__ == "radmon.archive_reports"


def test_lan_alarm_behavior_is_defined_in_base_modules():
    assert RemoteMariaDBSource.live_rows.__module__ == "radmon.lan"
    assert LanAggregator._run_live_core_once.__module__ == "radmon.lan"
    assert LanAggregator.run_live_once.__module__ == "radmon.lan"
    assert MariaCentralStore.mark_alarm_handled.__module__ == "radmon.lan"
    assert RemoteAlarmMirror.mirror.__module__ == "radmon.remote_alarm"
    assert RemoteAlarmMirror.reconcile_source_active_keys.__module__ == "radmon.remote_alarm"


def test_security_write_through_and_ack_are_defined_in_base_modules():
    assert SecurityStore.require_sensitive.__module__ == "radmon.security"
    assert SecurityStore.station_source.__module__ == "radmon.security"
    assert DeviceAdminService.update_station.__module__ == "radmon.device_admin"
    assert AlarmControlService.ack.__module__ == "radmon.remote_alarm"
    assert RemoteMariaDBSource.respond_alarm.__module__ == "radmon.lan"


def test_alarm_policy_behavior_is_defined_in_base_modules():
    assert AlarmPolicyService.process_cycle.__module__ == "radmon.alarm_policy"
    assert AlarmPolicyService.get_policy.__module__ == "radmon.alarm_policy"
    assert AlarmPolicyStore.start_suppression.__module__ == "radmon.alarm_policy_store"
    assert LanAggregator.run_live_once.__module__ == "radmon.lan"


def test_grafana_behavior_is_defined_in_base_modules():
    assert GrafanaBootstrap.ensure.__module__ == "radmon.grafana_bootstrap"
    assert grafana_tv._dose_stat.__module__ == "radmon.grafana_tv"
    assert grafana_tv._dose_sparkline.__module__ == "radmon.grafana_tv"
    assert grafana_tv._status_relation.__module__ == "radmon.grafana_tv"
    assert grafana_tv._operation_table.__module__ == "radmon.grafana_tv"
    assert grafana_tv.build_page_three.__module__ == "radmon.grafana_tv"


def test_admin_ui_behavior_is_defined_in_base_modules():
    assert PinDialog.get_pin.__module__ == "radmon.admin.auth_dialogs"
    assert MainWindow.reload_station_sidebar.__module__ == "radmon.admin.main_window"
    assert MainWindow.refresh_current_page.__module__ == "radmon.admin.main_window"
    assert StationAdminDialog.__init__.__module__ == "radmon.admin.station_admin_dialog"
    assert AlarmPage.__init__.__module__ == "radmon.admin.alarm_page"
    assert AlarmResponseDialog.__init__.__module__ == "radmon.admin.alarm_response_dialog"


def test_consolidated_revision_files_are_gone():
    for name in (
        "repository_revision.py",
        "archive_store_revision.py",
        "archive_reports_revision.py",
        "lan_revision.py",
        "remote_alarm_revision.py",
        "production_safety_revision.py",
        "production_integration_compat_revision.py",
        "alarm_policy_revision.py",
        "alarm_policy_store_revision.py",
        "alarm_policy_security_revision.py",
        "alarm_policy_runtime_revision.py",
        "grafana_bootstrap_revision.py",
        "grafana_policy_revision.py",
        "grafana_revision.py",
        "grafana_wib_revision.py",
        "icon_system_revision.py",
        "production_integration_revision.py",
    ):
        assert not (ROOT / "radmon" / name).exists()


def test_package_init_has_no_revision_dispatch():
    package_init = (ROOT / "radmon" / "__init__.py").read_text(encoding="utf-8")
    assert "_revision" not in package_init
    assert "apply as _apply" not in package_init


def test_one_shot_refactor_artifacts_are_gone():
    for relative in (
        "scripts/refactor_task7.py",
        "scripts/refactor_task7_fixed.py",
        "scripts/refactor_task8.py",
        "scripts/refactor_task9.py",
        "scripts/refactor_task10.py",
        ".github/workflows/refactor-task7.yml",
        ".github/workflows/refactor-task7-retry.yml",
        ".github/workflows/refactor-task7-repair.yml",
        ".github/workflows/task7-finalize.yml",
        ".github/workflows/refactor-task8.yml",
        ".github/workflows/task8-fix.yml",
        ".github/workflows/refactor-task9.yml",
        ".github/workflows/refactor-task9-retry.yml",
        ".github/workflows/refactor-task10.yml",
        "scripts/repair_task10.py",
        ".github/workflows/repair-task10.yml",
    ):
        assert not (ROOT / relative).exists()
