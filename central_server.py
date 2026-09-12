from __future__ import annotations

import argparse
import time

from radmon.central_service import CentralService
from radmon.config import Settings
from radmon.logging_setup import configure_logging


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Central measurement ingest and secure control server")
    value.add_argument("--host", default="0.0.0.0")
    value.add_argument("--port", type=int, default=8090)
    return value


def main() -> int:
    args = parser().parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    service = CentralService(settings, host=args.host, port=args.port)
    service.start()
    try:
        while service.running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
