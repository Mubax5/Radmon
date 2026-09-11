from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolBar, QMessageBox, QDialog

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
    source_health: Any | None = None
    alarm_policy: Any | None = None
    alarm_suppression: Any | None = None


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
    index = item.get("trigger_index")
    trigger = f" #{index}" if index else ""
    return (
        f"ALARM{trigger} · source {item.get('source_id') or 'central'} · "
        f"ID {item.get('serid')} · {measured_text} / threshold {threshold_text}"
    )


def _format_policy_status(item: dict[str, Any]) -> str:
    status = str(item.get("policy_state") or "NORMAL")
    underlying = str(item.get("underlying_dose_status") or "-")
    detail = f"[{status}] ID {item.get('serid')} · underlying {underlying}"
    if status == "SUPPRESSED":
        detail += (
            f" · PIC {item.get('suppression_pic') or '-'}"
            f" · reason {item.get('suppression_reason') or '-'}"
        )
    if item.get("retrigger_locked"):
        detail += " · RETRIGGER LOCKED"
    return detail


def _format_source_health(item: dict[str, Any]) -> str:
    state = str(item.get("state") or "UNKNOWN")
    message = f"[SERVER {state}] {item.get('source_id')} / {item.get('host')}"
    if item.get("last_error") and state in {"DEGRADED", "OFFLINE"}:
        message += f" - {item['last_error']}"
    return message


def install_window_security(window) -> None:
    context = get_context()
    if context is None:
        return

    from .admin.icons import app_icon

    user_label = QLabel(
        f"User: {context.identity.display_name} · {context.identity.role.value}"
    )
    user_label.setObjectName("securityIdentityLabel")
    window.statusBar().addPermanentWidget(user_label)

    def refresh_alarm_strip() -> None:
        recent_page = getattr(window, "recent_page", None)
        if recent_page is None or not hasattr(recent_page, "set_message_rows"):
            return
        message_rows: list[tuple[object, str]] = []
        try:
            if context.source_health is not None:
                for item in context.source_health.list_states():
                    if str(item.get("state")) != "CONNECTED":
                        message_rows.append((item.get("updated_at"), _format_source_health(item)))
            if context.alarm_policy is not None:
                rows = context.alarm_policy.list_events(active_only=True, limit=20)
                message_rows.extend(
                    (item.get("surfaced_at"), _format_active_alarm(item))
                    for item in rows
                    if str(item.get("kind")) == "ALARM"
                )
                try:
                    snapshot = context.alarm_policy.get_policy(int(window.settings.serid))
                    if snapshot.get("suppressed") or snapshot.get("retrigger_locked"):
                        message_rows.append((snapshot.get("updated_at"), _format_policy_status(snapshot)))
                except Exception:
                    pass
            else:
                rows = context.alarm_mirror.list_alarms(active_only=True, limit=20)
                message_rows.extend(
                    (item.get("event_time"), _format_active_alarm(item))
                    for item in rows
                )
            recent_page.set_message_rows(message_rows[:30])
        except Exception as exc:
            recent_page.set_message_rows([(None, f"Monitoring status unavailable: {exc}")])

    timer = QTimer(window)
    timer.setInterval(2000)
    timer.timeout.connect(refresh_alarm_strip)
    timer.start()
    window._security_alarm_timer = timer
    refresh_alarm_strip()

    security_menu = window.menuBar().addMenu("Security")
    toolbar = window.findChild(QToolBar, "mainToolbar")

    if context.identity.role is Role.ADMINISTRATOR:
        from .admin.station_admin_dialog import StationAdminDialog
        from .admin.user_admin_dialog import UserAdminDialog

        edit_station = QAction(app_icon("station_properties"), "Edit Station", window)
        manage_users = QAction(app_icon("users"), "Users", window)

        def open_station_editor() -> None:
            try:
                station = context.device_admin.repository.get_device(window.settings.serid)
                if station is None:
                    raise RuntimeError("station tidak ditemukan")
                dialog = StationAdminDialog(
                    context.device_admin, context.identity, station, window,
                    source=getattr(window, "source", "detector"),
                )
                if dialog.exec():
                    selected = window.station_tree.currentItem()
                    current = context.device_admin.repository.get_device(dialog.serid.value())
                    if selected is not None and current is not None:
                        selected.setText(0, str(current.get("name") or current["serid"]))
                        selected.setData(0, Qt.UserRole, int(current["serid"]))
                    if hasattr(window, "reload_station_sidebar"):
                        window.reload_station_sidebar(select_serid=dialog.serid.value())
                    else:
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

    if (
        context.identity.role in {Role.ADMINISTRATOR, Role.OPERATOR}
        and context.alarm_suppression is not None
        and context.alarm_policy is not None
    ):
        from .admin.suppression_dialog import SuppressionDialog

        suppress_action = QAction(app_icon("suppress_alarm"), "Suppress Alarm...", window)

        def open_suppression() -> None:
            try:
                serid = int(window.settings.serid)
                snapshot = context.alarm_policy.get_policy(serid)
                station = context.device_admin.repository.get_device(serid)
                station_name = (
                    str(station.get("name") or station.get("location") or serid)
                    if station else str(serid)
                )
                dialog = SuppressionDialog(
                    serid=serid,
                    station_name=station_name,
                    dose_rate=snapshot.get("measured_value"),
                    underlying_status=snapshot.get("underlying_dose_status") or "UNKNOWN",
                    default_pic=context.identity.display_name,
                    parent=window,
                )
                if dialog.exec() != QDialog.Accepted:
                    return
                context.alarm_suppression.start(
                    context.identity,
                    dialog.pin.text().strip(),
                    serid,
                    dialog.duration_seconds(),
                    dialog.pic.text().strip(),
                    dialog.reason.toPlainText().strip(),
                    dialog.auto_resume.isChecked(),
                )
                refresh_alarm_strip()
                if hasattr(window, "refresh_current_page"):
                    window.refresh_current_page()
            except Exception as exc:
                QMessageBox.warning(window, "Suppress Alarm", str(exc))

        suppress_action.triggered.connect(open_suppression)
        security_menu.addAction(suppress_action)
        if toolbar is not None:
            toolbar.addAction(suppress_action)
        window._suppress_alarm_action = suppress_action

    logout = QAction(app_icon("exit"), "Logout / Exit", window)

    def do_logout() -> None:
        context.audit.record("LOGOUT", context.identity, "user", context.identity.username)
        set_context(None)
        window.close()

    logout.triggered.connect(do_logout)
    security_menu.addSeparator()
    security_menu.addAction(logout)
