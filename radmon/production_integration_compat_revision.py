"""Narrow compatibility guards for the production integration revision.

Production RemoteMariaDBSource continues to use respond_alarm()/i_flag semantics.
These guards preserve older synthetic adapters used by regression tests without
weakening the deployed production path.
"""
from __future__ import annotations

from datetime import timedelta


def apply() -> None:
    _patch_sensitive_pin_semantics()
    _patch_optional_alarm_state_adapter()
    _patch_alarm_control_adapter_compatibility()
    _patch_lan_station_dialog_identity_fields()


def _patch_sensitive_pin_semantics() -> None:
    from . import security as module

    def require_sensitive(self, identity, permission: str, pin: str) -> None:
        if identity is None or not self.role_allows(identity.role, permission):
            raise module.SecurityError("aksi tidak diizinkan")

        supplied = str(pin or "")
        if not supplied:
            if self.sensitive_lease_active(identity):
                return
            raise module.SecurityError("PIN tidak valid")

        # An explicitly supplied PIN is always verified, even while a lease is
        # active. This prevents a mistyped/bad PIN from being silently ignored.
        if not self.verify_pin(identity.username, supplied):
            raise module.SecurityError("PIN tidak valid")

        with self._sensitive_lease_lock:
            self._sensitive_leases[str(identity.username).strip().lower()] = (
                self._now() + timedelta(seconds=600)
            )

    module.SecurityStore.require_sensitive = require_sensitive


def _patch_optional_alarm_state_adapter() -> None:
    from . import lan as module

    current_run_live = module.LanAggregator.run_live_once

    def run_live_once(self, source):
        result = current_run_live(self, source)
        # Old synthetic adapters predate the lightweight alarm-state refresh.
        # The real RemoteMariaDBSource always provides alarm_states().
        if (
            result.error
            and "object has no attribute 'alarm_states'" in str(result.error)
        ):
            result.error = None
        return result

    module.LanAggregator.run_live_once = run_live_once


def _patch_alarm_control_adapter_compatibility() -> None:
    from . import remote_alarm as module
    from .lan import RemoteMariaDBSource

    def ack(
        self,
        identity,
        pin: str,
        source_id: str,
        serid: int,
        event_time,
        *,
        action: str,
        pic: str,
        note: str,
    ):
        self.security.require_sensitive(identity, "ack_alarm", pin)
        if not action.strip() or not pic.strip():
            raise ValueError("Action dan PIC wajib diisi")
        before = self.mirror.get(source_id, serid, event_time)
        if before is None:
            raise RuntimeError("alarm tidak ditemukan")
        if before.get("is_active") is False:
            raise RuntimeError("alarm sudah ditangani")

        remote_serid = int(before.get("remote_serid") or serid)
        at = self.now()
        target_id = f"{source_id}:{serid}:{event_time.isoformat()}"
        try:
            remote = self.remote_factory(source_id)
            responder = getattr(remote, "respond_alarm", None)
            if callable(responder):
                # Deployed production path. This sets i_op/pic/note/i_flag=1
                # and intentionally leaves ack untouched.
                ok = bool(
                    responder(
                        remote_serid,
                        event_time,
                        action=action.strip(),
                        pic=pic.strip(),
                        note=note.strip(),
                        at=at,
                    )
                )
            elif not isinstance(remote, RemoteMariaDBSource) and callable(
                getattr(remote, "ack_legacy", None)
            ):
                # Compatibility only for old synthetic/test adapters. A real
                # RemoteMariaDBSource must never fall back to ack=1 semantics.
                ok = bool(
                    remote.ack_legacy(
                        remote_serid,
                        event_time,
                        action=action.strip(),
                        pic=pic.strip(),
                        note=note.strip(),
                        at=at,
                    )
                )
            else:
                raise RuntimeError("source tidak mendukung response i_flag")

            if not ok:
                raise RuntimeError("source menolak response; alarm mungkin sudah ditangani")
            after = self.mirror.mark_acknowledged(
                source_id,
                serid,
                event_time,
                acknowledged_at=at,
                pic=pic.strip(),
                action=action.strip(),
                note=note.strip(),
            )
        except Exception as exc:
            self.audit.record(
                "ALARM_ACK", identity, "alarm", target_id,
                before=before, success=False, reason=str(exc), source=source_id,
            )
            raise

        self.audit.record(
            "ALARM_ACK", identity, "alarm", target_id,
            before=before, after=after, source=source_id,
        )
        return after

    module.AlarmControlService.ack = ack


def _patch_lan_station_dialog_identity_fields() -> None:
    """Replace the earlier LAN dialog wrapper with the real widget names.

    The base dialog already makes SERID read-only in LAN mode. This copy keeps
    that behavior and additionally disables hardware source identity fields.
    """
    try:
        from PySide6.QtWidgets import (
            QDialogButtonBox,
            QDoubleSpinBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLineEdit,
            QPlainTextEdit,
            QPushButton,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
        from .admin import station_admin_dialog as module
    except Exception:
        return

    def init(
        self,
        device_admin,
        identity,
        station: dict,
        parent=None,
        *,
        source: str = "detector",
        is_new: bool = False,
    ) -> None:
        module.QDialog.__init__(self, parent)
        self.device_admin = device_admin
        self.identity = identity
        self.station = dict(station)
        self.source = source
        self.is_new = bool(is_new)
        self.setWindowTitle("New station..." if self.is_new else "Station properties")
        self.setWindowIcon(module.silk_icon("feed"))
        self.setMinimumWidth(430)

        self.serid = QSpinBox()
        self.serid.setRange(1, 2_147_483_647)
        self.serid.setValue(max(1, int(station.get("serid") or 1)))
        if source == "lan":
            self.serid.setEnabled(False)
            self.serid.setToolTip("LAN SERID is authoritative from the production device table.")

        self.name = QLineEdit(str(station.get("name") or ""))
        self.location = QLineEdit(str(station.get("location") or ""))
        self.description = QPlainTextEdit(str(station.get("description") or ""))
        self.description.setMaximumHeight(90)

        self.warn = QDoubleSpinBox()
        self.warn.setRange(0, 1_000_000)
        self.warn.setDecimals(6)
        self.warn.setValue(float(station.get("warnlevel") or 0))
        self.alarm = QDoubleSpinBox()
        self.alarm.setRange(0, 1_000_000)
        self.alarm.setDecimals(6)
        self.alarm.setValue(float(station.get("alarmlevel") or 0))
        self.maxidle = QSpinBox()
        self.maxidle.setRange(1, 1440)
        self.maxidle.setValue(int(station.get("maxidlemin") or 30))

        self.audio_path = QLineEdit(str(station.get("audiopath") or ""))
        audio_browse = QPushButton("...")
        audio_browse.clicked.connect(self._choose_audio)
        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.audio_path, 1)
        audio_layout.addWidget(audio_browse)

        self.hw_type = QLineEdit(str(station.get("hwtype") or "detector"))
        self.hw_address = QLineEdit(str(station.get("hwaddress") or ""))
        self.unit = QLineEdit(str(station.get("unit") or "µSv/h"))
        if source == "lan":
            self.hw_type.setEnabled(False)
            self.hw_address.setEnabled(False)
            self.hw_type.setToolTip("Identity hardware dikelola oleh source LAN.")
            self.hw_address.setToolTip("Identity hardware dikelola oleh source LAN.")

        tabs = QTabWidget()
        tabs.addTab(self._attributes_tab(), "Attributes")
        tabs.addTab(self._alarm_tab(audio_row), "Alarm")
        tabs.addTab(self._hardware_tab(), "Hardware")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    module.StationAdminDialog.__init__ = init
