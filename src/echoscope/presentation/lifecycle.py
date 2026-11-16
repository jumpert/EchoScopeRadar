"""Rotating activity logs for the browser-only background process."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(data_dir, *, practice=False):
    directory = Path(data_dir) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("practica.log" if practice else "echoscope.log")
    logger = logging.getLogger("echoscope")
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(
            target.resolve()
        ):
            return target
    handler = RotatingFileHandler(target, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return target
