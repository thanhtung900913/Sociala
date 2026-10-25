import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import Config

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _build_handlers() -> list[logging.Handler]:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(_formatter)
    handlers = [stdout_handler]

    if Config.LOG_FILE:
        Path(Config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            Config.LOG_FILE,
            maxBytes=50 * 1024 * 1024,  # 50 MB
            backupCount=5,
        )
        file_handler.setFormatter(_formatter)
        handlers.append(file_handler)

    return handlers


_handlers = _build_handlers()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        for handler in _handlers:
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
