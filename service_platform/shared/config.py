"""Environment-driven configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from service_platform.shared.constants import (
    DEFAULT_ALERT_LOG_PATH,
    DEFAULT_ALERT_THROTTLE_SECONDS,
    DEFAULT_ALERT_WEBHOOK_URL,
    DEFAULT_ANALYTICS_WINDOW_HOURS,
    DEFAULT_BACKUP_DIR,
    DEFAULT_FEEDBACK_ADMIN_KEY,
    DEFAULT_FEEDBACK_DB_PATH,
    DEFAULT_FEEDBACK_DUPLICATE_WINDOW_SECONDS,
    DEFAULT_FEEDBACK_MESSAGE_MIN_LENGTH,
    DEFAULT_FEEDBACK_RATE_LIMIT_SECONDS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PUBLIC_DATA_DIR,
    DEFAULT_PUBLISH_KEEP_DAYS,
    DEFAULT_S2_HOLDINGS_CSV,
    DEFAULT_S2_SNAPSHOT_CSV,
    DEFAULT_S2_SUMMARY_CSV,
    DEFAULT_SNAPSHOT_CACHE_TTL_SECONDS,
    DEFAULT_SNAPSHOT_GCS_BASE_URL,
    DEFAULT_SNAPSHOT_GCS_BUCKET,
    DEFAULT_SNAPSHOT_SOURCE,
    DEFAULT_SNAPSHOT_STALE_AFTER_HOURS,
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
    publish_root_dir: Path
    feedback_db_path: Path
    backup_dir: Path
    alert_log_path: Path
    alert_webhook_url: str
    alert_throttle_seconds: int
    log_level: str
    publish_keep_days: int
    snapshot_source: str
    snapshot_cache_ttl_seconds: int
    snapshot_stale_after_hours: int
    snapshot_gcs_bucket: str
    snapshot_gcs_base_url: str
    feedback_rate_limit_seconds: int
    feedback_duplicate_window_seconds: int
    feedback_message_min_length: int
    feedback_admin_key: str
    analytics_window_hours: int
    s2_holdings_csv: Path
    s2_snapshot_csv: Path
    s2_summary_csv: Path


def _get_port() -> int:
    raw_port = os.getenv("PORT") or os.getenv("WEB_PORT") or str(DEFAULT_WEB_PORT)
    return int(raw_port)


def get_settings() -> Settings:
    public_data_dir = Path(os.getenv("PUBLIC_DATA_DIR", str(DEFAULT_PUBLIC_DATA_DIR)))
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        web_host=os.getenv("WEB_HOST", DEFAULT_WEB_HOST),
        web_port=_get_port(),
        public_data_dir=public_data_dir,
        publish_root_dir=Path(os.getenv("PUBLISH_ROOT_DIR", str(public_data_dir))),
        feedback_db_path=Path(os.getenv("FEEDBACK_DB_PATH", str(DEFAULT_FEEDBACK_DB_PATH))),
        backup_dir=Path(os.getenv("BACKUP_DIR", str(DEFAULT_BACKUP_DIR))),
        alert_log_path=Path(os.getenv("ALERT_LOG_PATH", str(DEFAULT_ALERT_LOG_PATH))),
        alert_webhook_url=os.getenv("ALERT_WEBHOOK_URL", DEFAULT_ALERT_WEBHOOK_URL),
        alert_throttle_seconds=int(
            os.getenv("ALERT_THROTTLE_SECONDS", str(DEFAULT_ALERT_THROTTLE_SECONDS))
        ),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        publish_keep_days=int(os.getenv("PUBLISH_KEEP_DAYS", str(DEFAULT_PUBLISH_KEEP_DAYS))),
        snapshot_source=os.getenv("SNAPSHOT_SOURCE", DEFAULT_SNAPSHOT_SOURCE),
        snapshot_cache_ttl_seconds=int(
            os.getenv("SNAPSHOT_CACHE_TTL_SECONDS", str(DEFAULT_SNAPSHOT_CACHE_TTL_SECONDS))
        ),
        snapshot_stale_after_hours=int(
            os.getenv("SNAPSHOT_STALE_AFTER_HOURS", str(DEFAULT_SNAPSHOT_STALE_AFTER_HOURS))
        ),
        snapshot_gcs_bucket=os.getenv("SNAPSHOT_GCS_BUCKET", DEFAULT_SNAPSHOT_GCS_BUCKET),
        snapshot_gcs_base_url=os.getenv("SNAPSHOT_GCS_BASE_URL", DEFAULT_SNAPSHOT_GCS_BASE_URL),
        feedback_rate_limit_seconds=int(
            os.getenv("FEEDBACK_RATE_LIMIT_SECONDS", str(DEFAULT_FEEDBACK_RATE_LIMIT_SECONDS))
        ),
        feedback_duplicate_window_seconds=int(
            os.getenv(
                "FEEDBACK_DUPLICATE_WINDOW_SECONDS",
                str(DEFAULT_FEEDBACK_DUPLICATE_WINDOW_SECONDS),
            )
        ),
        feedback_message_min_length=int(
            os.getenv("FEEDBACK_MESSAGE_MIN_LENGTH", str(DEFAULT_FEEDBACK_MESSAGE_MIN_LENGTH))
        ),
        feedback_admin_key=os.getenv("FEEDBACK_ADMIN_KEY", DEFAULT_FEEDBACK_ADMIN_KEY),
        analytics_window_hours=int(
            os.getenv("ANALYTICS_WINDOW_HOURS", str(DEFAULT_ANALYTICS_WINDOW_HOURS))
        ),
        s2_holdings_csv=Path(os.getenv("S2_HOLDINGS_CSV", str(DEFAULT_S2_HOLDINGS_CSV))),
        s2_snapshot_csv=Path(os.getenv("S2_SNAPSHOT_CSV", str(DEFAULT_S2_SNAPSHOT_CSV))),
        s2_summary_csv=Path(os.getenv("S2_SUMMARY_CSV", str(DEFAULT_S2_SUMMARY_CSV))),
    )
