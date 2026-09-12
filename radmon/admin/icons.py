from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


ICON_SLOTS: dict[str, str] = {
    "monitoring": "chart-line",
    "station_group": "server",
    "detector": "radioactive",
    "recent": "activity",
    "tabular": "database",
    "chart": "chart-area-line",
    "reports": "file-chart",
    "alarm": "alarm",
    "suppress_alarm": "bell-cancel",
    "logs": "logs",
    "station_properties": "settings-cog",
    "users": "users",
    "archive": "archive",
    "refresh": "refresh",
    "server_test": "server-cog",
    "hardware_test": "cpu-2",
    "acquisition": "device-analytics",
    "installation_manual": "book-2",
    "user_manual": "help-circle",
    "exit": "logout",
    "save_as": "file-export",
    "save_csv": "table-export",
    "printer_setup": "settings-2",
    "print_preview": "eye-check",
    "print": "printer",
    "select_period": "calendar",
    "new_station": "plus",
    "application_options": "settings",
    "about": "file-info",
}

_TABLER_ROOT = Path(__file__).with_name("icons") / "tabler"


def icon_path(slot: str) -> Path:
    icon_id = ICON_SLOTS[slot]
    return _TABLER_ROOT / f"{icon_id}.svg"


def app_icon(slot: str) -> QIcon:
    path = icon_path(slot)
    if not path.is_file():
        raise FileNotFoundError(f"Tabler icon asset missing for {slot}: {path}")
    return QIcon(str(path))
