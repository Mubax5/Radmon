"""Real detector collector entry point.

This is the modular replacement for the user's original COM15 -> MariaDB script.
The protocol is intentionally preserved while the station ID becomes configurable
and defaults to the requested demo station 5202 / IS-1 Koridor.
"""

from radmon.alarm import AlarmService
from radmon.collector import SerialCollector
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.repository import MariaDBRepository


def main() -> int:
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    repository = MariaDBRepository(settings)
    station = repository.station_config(settings.serid)
    alarms = AlarmService(repository, station)
    print(f"Monitoring detector dimulai: {settings.station_label}")
    print(f"Serial: {settings.serial_port} @ {settings.baudrate} baud")
    SerialCollector(settings, repository, alarms).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
