"""Generate demo measurements for Gedung 52 / IS-1 Koridor every two seconds."""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
import time

from radmon.alarm import AlarmService
from radmon.config import Settings
from radmon.dummy import DummyDoseGenerator
from radmon.logging_setup import configure_logging
from radmon.models import Measurement
from radmon.repository import MariaDBRepository

LOGGER = logging.getLogger("radmon.dummy_cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(DummyDoseGenerator.MODES), default="mixed")
    parser.add_argument("--interval", type=float, default=None, help="seconds between samples; default from .env (2)")
    parser.add_argument("--count", type=int, default=0, help="number of samples; 0 means run forever")
    parser.add_argument("--seed", type=int, default=None, help="deterministic random seed")
    parser.add_argument("--write-raw", action="store_true", help="also insert simulated ASCII into rawdata")
    return parser


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    interval = args.interval if args.interval is not None else settings.sample_interval
    if interval <= 0:
        raise SystemExit("--interval must be positive")
    if args.count < 0:
        raise SystemExit("--count cannot be negative")

    repository = MariaDBRepository(settings)
    station = repository.station_config(settings.serid)
    alarms = AlarmService(repository, station)
    generator = DummyDoseGenerator(
        args.mode,
        seed=args.seed,
        warnlevel=station.warnlevel,
        alarmlevel=station.alarmlevel,
    )
    LOGGER.info(
        "dummy started station=%s mode=%s interval=%.2fs count=%s",
        settings.station_label,
        args.mode,
        interval,
        "infinite" if args.count == 0 else args.count,
    )
    index = 0
    try:
        while args.count == 0 or index < args.count:
            dose = generator.next_value()
            when = datetime.now()
            measurement = Measurement(
                serid=settings.serid,
                measured_at=when,
                dose_rate=dose,
                previnterval=max(1, int(round(interval))),
                stat=0,
            )
            raw = f"{dose:07.3f} DEMO" if args.write_raw else None
            repository.insert_measurement(measurement, raw=raw, queue_sync=True)
            state = alarms.evaluate(measurement)
            print(f"{when:%Y-%m-%d %H:%M:%S} | {settings.station_label} | {dose:.3f} µSv/h | {state}")
            index += 1
            if args.count == 0 or index < args.count:
                time.sleep(interval)
    except KeyboardInterrupt:
        LOGGER.info("dummy stopped by operator")
    return 0


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
