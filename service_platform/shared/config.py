"""Environment-driven configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from service_platform.shared.constants import (
    DEFAULT_FEEDBACK_DB_PATH,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PUBLIC_DATA_DIR,
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
)

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str
    web_host: str
    web_port: int
    public_data_dir: Path
    feedback_db_path: Path
    log_level: str


def get_settings() -> Settings:
    """Load settings from environment variables with documented defaults."""

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        web_host=os.getenv("WEB_HOST", DEFAULT_WEB_HOST),
        web_port=int(os.getenv("WEB_PORT", str(DEFAULT_WEB_PORT))),
        public_data_dir=Path(os.getenv("PUBLIC_DATA_DIR", str(DEFAULT_PUBLIC_DATA_DIR))),
        feedback_db_path=Path(os.getenv("FEEDBACK_DB_PATH", str(DEFAULT_FEEDBACK_DB_PATH))),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
    )
