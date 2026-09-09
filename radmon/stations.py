from __future__ import annotations

from .models import StationConfig


STATION_CATALOG: tuple[StationConfig, ...] = (
    StationConfig(3000, "50", "R. Resin Penukar Ion", "Gd.50", 100.0, 150.0, 30, "µSv/h"),
    StationConfig(3001, "50", "R. Evaporasi", "Gd.50", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3002, "50", "R. Kompaksi", "Gd.50", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3003, "50", "R. Sementasi", "Gd.50", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3004, "50", "R. Insenerasi", "Gd.50", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3801, "38", "Kolam", "Gd.38", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3802, "38", "Purifikasi", "Gd.38", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3803, "38", "Pintu Kanal", "Gd.38", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3804, "38", "Kanal Masuk", "Gd.38", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(3805, "38", "Kanal Utama", "Gd.38", 8.0, 10.0, 30, "µSv/h"),
    StationConfig(5201, "52", "IS-1", "Gd.52", 23.0, 25.0, 30, "µSv/h"),
    StationConfig(5202, "52", "IS-1 Koridor", "Gd.52", 23.0, 25.0, 30, "µSv/h"),
    StationConfig(5501, "55", "PSLAT", "Gd.55", 23.0, 25.0, 30, "µSv/h"),
    StationConfig(5701, "57", "IS-2", "Gd.57", 23.0, 25.0, 30, "µSv/h"),
    StationConfig(5702, "57", "IS-2 LBN", "Gd.57", 23.0, 25.0, 30, "µSv/h"),
)


def station_catalog() -> list[StationConfig]:
    """Return the production-aligned detector catalog in display order."""
    return list(STATION_CATALOG)


def station_by_id(serid: int) -> StationConfig | None:
    for station in STATION_CATALOG:
        if station.serid == serid:
            return station
    return None
