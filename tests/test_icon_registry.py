import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


def app():
    return QApplication.instance() or QApplication([])


def test_all_registry_icons_are_local_tabler_svg_and_load():
    from radmon.admin.icons import ICON_SLOTS, app_icon, icon_path

    app()
    for slot in ICON_SLOTS:
        path = icon_path(slot)
        assert path.parent.name == "tabler"
        assert path.suffix == ".svg"
        assert path.is_file(), slot
        assert not app_icon(slot).isNull(), slot


def test_primary_feature_slots_are_semantically_unique():
    from radmon.admin.icons import icon_path

    slots = [
        "monitoring", "station_group", "detector", "recent", "tabular",
        "chart", "reports", "alarm", "suppress_alarm", "logs",
        "station_properties", "users", "archive", "refresh", "server_test",
        "hardware_test", "acquisition", "installation_manual", "user_manual", "exit",
    ]
    paths = [icon_path(slot).name for slot in slots]
    assert len(paths) == len(set(paths))


def test_settings_related_commands_do_not_share_icons():
    from radmon.admin.icons import icon_path

    names = {
        icon_path("station_properties").name,
        icon_path("application_options").name,
        icon_path("printer_setup").name,
    }
    assert len(names) == 3


def test_unknown_slot_fails_loudly():
    from radmon.admin.icons import app_icon

    with pytest.raises(KeyError):
        app_icon("not-a-real-slot")
