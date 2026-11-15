"""Merkezi loglama: hem konsola hem logs/kariyer_otonomu.log dosyasına yazar."""
import logging
from logging.handlers import RotatingFileHandler

from app.settings import LOG_FILE, LOG_LEVEL

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(LOG_LEVEL)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False
    return logger


def read_recent_logs(lines: int = 200) -> str:
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            return "".join(f.readlines()[-lines:])
    except FileNotFoundError:
        return ""
