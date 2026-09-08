from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QLabel, QToolBar, QMessageBox

from .audit import AuditTrail
from .security import Role, SecurityStore, UserIdentity


@dataclass(slots=True)
class SecurityContext:
    identity: UserIdentity
    security: SecurityStore
    audit: AuditTrail
    alarm_mirror: Any
    alarm_control: Any
    device_admin: Any
    user_admin: Any


_context: SecurityContext | None = None


def set_context(value: SecurityContext | None) -> None:
    global _context
    _context = value


def get_context() -> SecurityContext | None:
    return _context


def _format_active_alarm(item: dict[str, Any]) -> str:
    measured = item.get("measured_value")
    threshold = item.get("threshold")
    measured_text = "-" if measured is None else f"{float(measured):.3f} µSv/h"
    threshold_text = "-" if threshold is None else f"{float(threshold):.3f} µSv/h"
    when = item.get("event_time")
    when_text = when.strftime("%d/%m/%Y %H:%M:%S") if hasattr(when, "strftime") else str(when or "-")
    return (
        f"<b>{item.get('level', 'ALARM')}</b> · source {item.get('source_id')} · "
        f"ID {item.get('serid')} · {measured_text} / threshold {threshold_text} · {when_text}"
    )


def install_window_security(window) -> None:
    context = get_context()
    if context is None:
        return

    user_label = QLabel(
        f"User: {context.identity.display_name} · {context.identity.role.value}"
    )
    user_label.setObjectName("securityIdentityLabel")
    window.statusBar().addPermanentWidget(user_label)

    dock = QDockWidget("Active Alarm", window)
    dock.setObjectName("activeAlarmDock")
    dock.setAllowedAreas(Qt.BottomDockWidgetArea)
    alarm_label = QLabel("Tidak ada alarm aktif.")
    alarm_label.setObjectName("activeAlarmMessage")
    alarm_label.setTextFormat(Qt.RichText)
    alarm_label.setMargin(6)
    dock.setWidget(alarm_label)
    window.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def refresh_alarm_strip() -> None:
        try:
            rows = context.alarm_mirror.list_alarms(active_only=True, limit=1)
            alarm_label.setText(_format_active_alarm(rows[0]) if rows else "Tidak ada alarm aktif.")
        except Exception as exc:
            alarm_label.setText(f"Alarm status unavailable: {exc}")

    timer = QTimer(window)
    timer.setInterval(2000)
    timer.timeout.connect(refresh_alarm_strip)
    timer.start()
    window._security_alarm_timer = timer
    refresh_alarm_strip()

    security_menu = window.menuBar().addMenu("Security")
    toolbar = window.findChild(QToolBar, "mainToolbar")

    if context.identity.role is Role.ADMINISTRATOR:
        from .admin.icons import silk_icon
        from .admin.station_admin_dialog import StationAdminDialog
        from .admin.user_admin_dialog import UserAdminDialog

        edit_station = QAction(silk_icon("feed"), "Edit Station", window)
        manage_users = QAction(silk_icon("lock"), "Users", window)

        def open_station_editor() -> None:
            try:
                station = context.device_admin.repository.get_device(window.settings.serid)
                if station is None:
                    raise RuntimeError("station tidak ditemukan")
                dialog = StationAdminDialog(context.device_admin, context.identity, station, window)
                if dialog.exec():
                    selected = window.station_tree.currentItem()
                    current = context.device_admin.repository.get_device(dialog.serid.value())
                    if selected is not None and current is not None:
                        selected.setText(0, str(current.get("name") or current["serid"]))
                        selected.setData(0, Qt.UserRole, int(current["serid"]))
                    window.refresh_current_page()
            except Exception as exc:
                QMessageBox.warning(window, "Edit Station", str(exc))

        edit_station.triggered.connect(open_station_editor)
        manage_users.triggered.connect(
            lambda: UserAdminDialog(
                context.user_admin, context.security, context.identity, window
            ).exec()
        )
        security_menu.addAction(edit_station)
        security_menu.addAction(manage_users)
        if toolbar is not None:
            toolbar.addSeparator()
            toolbar.addAction(edit_station)
            toolbar.addAction(manage_users)

    logout = QAction("Logout / Exit", window)

    def do_logout() -> None:
        context.audit.record(
            "LOGOUT", context.identity, "user", context.identity.username
        )
        set_context(None)
        window.close()

    logout.triggered.connect(do_logout)
    security_menu.addSeparator()
    security_menu.addAction(logout)
