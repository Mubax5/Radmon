from __future__ import annotations

import importlib
from typing import Any, Callable

from .config import Settings


def database_row_value(row: Any, column: str, index: int) -> Any:
    """Read a column from either a mapping or a positional DB result row."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(column)
    return row[index]


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
