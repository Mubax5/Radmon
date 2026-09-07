from pathlib import Path

from radmon.stations import STATION_CATALOG, station_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_reference_station_catalog_contains_all_detector_rooms():
    stations = station_catalog()
    assert [station.serid for station in stations] == [
        3000,
        3001,
        3002,
        3004,
        3009,
        3801,
        3802,
        3803,
        3804,
        3805,
        5201,
        5202,
        5601,
        5701,
        5702,
    ]
    expected = {
        3000: ("Resin Penukar Ion", "Gd.50"),
        3001: ("R. Evaporasi", "Gd.50"),
        3002: ("R. Kompaksi", "Gd.50"),
        3004: ("R. Insenerasi", "Gd.50"),
        3009: ("R. Sementasi", "Gd.50"),
        3801: ("R. Kolam", "Gd.38"),
        3802: ("R. Purifikasi", "Gd.38"),
        3803: ("R. Pintu Masuk Kanal", "Gd.38"),
        3804: ("R. Kanal Masuk", "Gd.38"),
        3805: ("R. Kanal Utama", "Gd.38"),
        5201: ("IS-1", "Gd.52"),
        5202: ("IS-1 Koridor", "Gd.52"),
        5601: ("PSLAT", "Gd.55"),
        5701: ("IS-2", "Gd.57"),
        5702: ("IS-2 LBN", "Gd.57"),
    }
    assert len(STATION_CATALOG) == len(expected)
    for station in stations:
        assert (station.room, station.location) == expected[station.serid]
        assert station.unit == "µSv/h"


def test_reference_thresholds_match_monitoring_reference():
    by_id = {station.serid: station for station in station_catalog()}
    assert (by_id[3000].warnlevel, by_id[3000].alarmlevel) == (100.0, 150.0)
    assert (by_id[5201].warnlevel, by_id[5201].alarmlevel) == (23.0, 25.0)
    assert (by_id[5601].warnlevel, by_id[5601].alarmlevel) == (23.0, 25.0)
    for serid in (3001, 3002, 3004, 3009, 3801, 3802, 3803, 3804, 3805, 5202, 5701, 5702):
        assert (by_id[serid].warnlevel, by_id[serid].alarmlevel) == (8.0, 10.0)


def test_admin_uses_station_parent_tree_instead_of_single_flat_list():
    source = (ROOT / "radmon/admin/main_window.py").read_text(encoding="utf-8")
    assert "QTreeWidget" in source
    assert "QTreeWidgetItem" in source
    assert '"Station"' in source
    assert "station_configs" in source
    assert "currentItemChanged" in source
