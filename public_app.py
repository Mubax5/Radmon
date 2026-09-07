from __future__ import annotations

import argparse

import uvicorn

from radmon.config import Settings
from radmon.logging_setup import configure_logging
from radmon.public_api import create_public_app
from radmon.repository import MariaDBRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only fullscreen Radmon public monitoring server.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser


def build_app():
    settings = Settings.from_env()
    return create_public_app(MariaDBRepository(settings), settings)


app = build_app()


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_dir)
    uvicorn.run(
        "public_app:app",
        host=args.host or settings.public_host,
        port=args.port or settings.public_port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
