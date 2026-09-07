from __future__ import annotations

import importlib
from typing import Any, Callable

from .config import Settings


def connect_mariadb(settings: Settings) -> Any:
    mariadb = importlib.import_module("mariadb")
    return mariadb.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        autocommit=False,
    )


def connection_factory(settings: Settings) -> Callable[[], Any]:
    return lambda: connect_mariadb(settings)
