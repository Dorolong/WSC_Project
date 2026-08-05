import logging
import os
import sys
from logging.handlers import RotatingFileHandler


MAX_LOG_BYTES = 20 * 1024 * 1024
BACKUP_COUNT = 10


def setup_logging(logs_dir: str, name: str = "wsc.server") -> logging.Logger:
    """Configure server logging once and return the shared logger."""
    os.makedirs(logs_dir, exist_ok=True)

    logger = logging.getLogger(name)
    if getattr(logger, "_wsc_logging_configured", False):
        return logger

    level_name = os.environ.get("WSC_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "server.log"),
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger._wsc_logging_configured = True
    return logger
