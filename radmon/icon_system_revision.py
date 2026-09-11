"""Final semantic icon pass applied after legacy production compatibility patches."""
from __future__ import annotations

from PySide6.QtCore import Qt


def apply() -> None:
    from .admin import main_window
    from .admin.icons import app_icon
    from .admin import station_admin_dialog

    previous_reload = main_window.MainWindow.reload_station_sidebar

    def reload_station_sidebar(self, *args, **kwargs):
        result = previous_reload(self, *args, **kwargs)
        tree = getattr(self, "station_tree", None)
        if tree is None:
            return result

        def assign(item) -> None:
            serid = item.data(0, Qt.UserRole)
            if serid is not None:
                item.setIcon(0, app_icon("detector"))
            else:
                item.setIcon(0, app_icon("station_group"))
            for index in range(item.childCount()):
                assign(item.child(index))

        for index in range(tree.topLevelItemCount()):
            assign(tree.topLevelItem(index))
        return result

    main_window.MainWindow.reload_station_sidebar = reload_station_sidebar

    previous_station_init = station_admin_dialog.StationAdminDialog.__init__

    def station_init(self, *args, **kwargs):
        previous_station_init(self, *args, **kwargs)
        self.setWindowIcon(app_icon("station_properties"))

    station_admin_dialog.StationAdminDialog.__init__ = station_init
