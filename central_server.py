from __future__ import annotations

import argparse
import uvicorn

from radmon.central_api import CentralMariaDBRepository, create_central_app
from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.repository import MariaDBRepository


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Central measurement ingest server")
    value.add_argument("--host", default="0.0.0.0")
    value.add_argument("--port", type=int, default=8090)
    return value


def main() -> int:
    args = parser().parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    MariaDBRepository(settings).require_schema()
    app = create_central_app(CentralMariaDBRepository(settings), settings)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
