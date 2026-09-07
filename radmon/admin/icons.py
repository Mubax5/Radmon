from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


_ICON_ROOT = Path(__file__).with_name("icons") / "silk"


def silk_path(name: str) -> Path:
    return _ICON_ROOT / f"{name}.png"


def silk_icon(name: str) -> QIcon:
    path = silk_path(name)
    return QIcon(str(path)) if path.is_file() else QIcon()
