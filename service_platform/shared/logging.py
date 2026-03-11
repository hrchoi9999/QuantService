"""Logging configuration helpers."""

from __future__ import annotations

import logging
from pathlib import Path


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "service": getattr(record, "service", "app"),
            "message": record.getMessage(),
        }
        optional_fields = ["run_id", "request_id", "asof", "status", "error_code"]
        for field in optional_fields:
            value = getattr(record, field, None)
            if value is not None and value != "":
                base[field] = value
        return " ".join(f"{key}={value}" for key, value in base.items())


def configure_logging(log_level: str, log_path: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("quantservice")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = KeyValueFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
