from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_dir: Path | str, level: int = logging.INFO) -> Path:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "radmon.log"
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(path.resolve()) for handler in root.handlers):
        file_handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(file_handler)
    if not any(type(handler) is logging.StreamHandler for handler in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        root.addHandler(console)
    return path
