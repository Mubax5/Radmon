from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from radmon.admin.station_admin_dialog import StationAdminDialog


def test_lan_station_dialog_keeps_source_identity_read_only():
    app = QApplication.instance() or QApplication([])
    station = {
        "serid": 3000,
        "name": "R. Resin Penukar Ion",
        "location": "Gd.50",
        "description": "",
        "warnlevel": 100.0,
        "alarmlevel": 150.0,
        "maxidlemin": 30,
        "unit": "µSv/h",
        "audiopath": "",
        "hwaddress": "gd50",
        "hwtype": "remote",
    }
    dialog = StationAdminDialog(
        SimpleNamespace(),
        SimpleNamespace(username="admin"),
        station,
        source="lan",
    )
    assert dialog.serid.isEnabled() is False
    assert dialog.hw_address.isEnabled() is False
    assert dialog.hw_type.isEnabled() is False
    values = dialog._values()
    assert "hwaddress" not in values
    assert "hwtype" not in values
    dialog.close()
    assert app is not None
