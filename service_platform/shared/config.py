"""Environment-driven configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

from service_platform.shared.constants import (
    DEFAULT_ALERT_LOG_PATH,
    DEFAULT_ALERT_THROTTLE_SECONDS,
    DEFAULT_ALERT_WEBHOOK_URL,
    DEFAULT_ALLOW_HIGHER_PLAN_DURING_TRIAL,
    DEFAULT_ANALYTICS_PREVIEW_ALLOWED_EMAILS,
    DEFAULT_ANALYTICS_WINDOW_HOURS,
    DEFAULT_APP_DB_PATH,
    DEFAULT_BACKUP_DIR,
    DEFAULT_BILLING_CURRENCY,
    DEFAULT_BILLING_CYCLE_DAYS,
    DEFAULT_BILLING_ENABLED,
    DEFAULT_BILLING_MODE,
    DEFAULT_BOOTSTRAP_ADMIN_EMAIL,
    DEFAULT_BOOTSTRAP_ADMIN_PASSWORD,
    DEFAULT_FEEDBACK_ADMIN_KEY,
    DEFAULT_FEEDBACK_DB_PATH,
    DEFAULT_FEEDBACK_DUPLICATE_WINDOW_SECONDS,
    DEFAULT_FEEDBACK_MESSAGE_MIN_LENGTH,
    DEFAULT_FEEDBACK_RATE_LIMIT_SECONDS,
    DEFAULT_INTERNAL_PREVIEW_ENABLED,
    DEFAULT_INVESTMENT_GCS_BUCKET,
    DEFAULT_INVESTMENT_GCS_PREFIX,
    DEFAULT_INVESTMENT_PRICE_DB_PATH,
    DEFAULT_INVESTMENT_STORAGE_SOURCE,
    DEFAULT_LIGHTPAY_MERCHANT_KEY,
    DEFAULT_LIGHTPAY_MID,
    DEFAULT_LIGHTPAY_NOTIFY_ALLOWED_IPS,
    DEFAULT_LIGHTPAY_NOTIFY_URL,
    DEFAULT_LIGHTPAY_RETURN_URL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_CODE_TTL_SECONDS,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_ENABLED,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_EMAIL,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_NAME,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_MODE,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_PREVIEW_ENABLED,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_HOST,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PASSWORD,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PORT,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_SSL,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_STARTTLS,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS,
    DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_USERNAME,
    DEFAULT_MARKET_ANALYSIS_BASE_URL,
    DEFAULT_MARKET_ANALYSIS_DIR,
    DEFAULT_MARKET_ANALYSIS_SOURCE,
    DEFAULT_PHONE_VERIFICATION_CODE_TTL_SECONDS,
    DEFAULT_PHONE_VERIFICATION_MODE,
    DEFAULT_PHONE_VERIFICATION_PREVIEW_ENABLED,
    DEFAULT_PRODUCTION_SNAPSHOT_GCS_BASE_URL,
    DEFAULT_PRODUCTION_SNAPSHOT_SOURCE,
    DEFAULT_PUBLIC_DATA_DIR,
    DEFAULT_PUBLISH_KEEP_DAYS,
    DEFAULT_S2_HOLDINGS_CSV,
    DEFAULT_S2_SNAPSHOT_CSV,
    DEFAULT_S2_SUMMARY_CSV,
    DEFAULT_SESSION_SECRET_KEY,
    DEFAULT_SNAPSHOT_CACHE_TTL_SECONDS,
    DEFAULT_SNAPSHOT_GCS_BASE_URL,
    DEFAULT_SNAPSHOT_GCS_BUCKET,
    DEFAULT_SNAPSHOT_SOURCE,
    DEFAULT_SNAPSHOT_STALE_AFTER_HOURS,
    DEFAULT_TRIAL_APPLIES_TO,
    DEFAULT_TRIAL_DEFAULT_PLAN,
    DEFAULT_TRIAL_END_DATE,
    DEFAULT_TRIAL_MODE,
    DEFAULT_TSERIES_OPERATIONAL_DB_PATH,
    DEFAULT_UI_REDESIGN_ENABLED,
    DEFAULT_UI_THEME_DEFAULT,
    DEFAULT_USER_SNAPSHOT_DIR,
    DEFAULT_WEB_HOST,
    DEFAULT_WEB_PORT,
)

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str
    web_host: str
    web_port: int
    session_secret_key: str
    public_data_dir: Path
    publish_root_dir: Path
    feedback_db_path: Path
    app_db_path: Path
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
    internal_preview_enabled: bool
    analytics_preview_allowed_emails: tuple[str, ...]
    trial_mode: bool
    trial_default_plan: str
    trial_end_date: str
    trial_applies_to: str
    allow_higher_plan_during_trial: bool
    billing_enabled: bool
    billing_mode: str
    billing_cycle_days: int
    billing_currency: str
    lightpay_mid: str
    lightpay_merchant_key: str
    lightpay_return_url: str
    lightpay_notify_url: str
    lightpay_notify_allowed_ips: tuple[str, ...]
    phone_verification_mode: str
    phone_verification_code_ttl_seconds: int
    phone_verification_preview_enabled: bool
    s2_holdings_csv: Path
    s2_snapshot_csv: Path
    s2_summary_csv: Path
    user_snapshot_dir: Path = DEFAULT_USER_SNAPSHOT_DIR
    market_analysis_dir: Path = DEFAULT_MARKET_ANALYSIS_DIR
    market_analysis_source: str = DEFAULT_MARKET_ANALYSIS_SOURCE
    market_analysis_base_url: str = DEFAULT_MARKET_ANALYSIS_BASE_URL
    tseries_operational_db_path: Path = DEFAULT_TSERIES_OPERATIONAL_DB_PATH
    investment_price_db_path: Path = DEFAULT_INVESTMENT_PRICE_DB_PATH
    investment_storage_source: str = DEFAULT_INVESTMENT_STORAGE_SOURCE
    investment_gcs_bucket: str = DEFAULT_INVESTMENT_GCS_BUCKET
    investment_gcs_prefix: str = DEFAULT_INVESTMENT_GCS_PREFIX
    ui_redesign_enabled: bool = DEFAULT_UI_REDESIGN_ENABLED
    ui_theme_default: str = DEFAULT_UI_THEME_DEFAULT
    bootstrap_admin_email: str = DEFAULT_BOOTSTRAP_ADMIN_EMAIL
    bootstrap_admin_password: str = DEFAULT_BOOTSTRAP_ADMIN_PASSWORD
    login_email_verification_enabled: bool = DEFAULT_LOGIN_EMAIL_VERIFICATION_ENABLED
    login_email_verification_mode: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_MODE
    login_email_verification_code_ttl_seconds: int = (
        DEFAULT_LOGIN_EMAIL_VERIFICATION_CODE_TTL_SECONDS
    )
    login_email_verification_preview_enabled: bool = (
        DEFAULT_LOGIN_EMAIL_VERIFICATION_PREVIEW_ENABLED
    )
    login_email_verification_smtp_host: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_HOST
    login_email_verification_smtp_port: int = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PORT
    login_email_verification_smtp_ssl: bool = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_SSL
    login_email_verification_smtp_starttls: bool = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_STARTTLS
    login_email_verification_smtp_username: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_USERNAME
    login_email_verification_smtp_password: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PASSWORD
    login_email_verification_from_email: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_EMAIL
    login_email_verification_from_name: str = DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_NAME
    login_email_verification_smtp_timeout_seconds: int = (
        DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS
    )


def _get_port() -> int:
    raw_port = os.getenv("PORT") or os.getenv("WEB_PORT") or str(DEFAULT_WEB_PORT)
    return int(raw_port)


def _get_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_csv_tuple(name: str, default: str = "") -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return tuple(values)


def _get_theme_default() -> str:
    raw_value = str(os.getenv("UI_THEME_DEFAULT", DEFAULT_UI_THEME_DEFAULT)).strip().lower()
    if raw_value not in {"light", "dark", "system"}:
        return DEFAULT_UI_THEME_DEFAULT
    return raw_value


def _normalize_snapshot_runtime(settings: Settings) -> Settings:
    snapshot_source = settings.snapshot_source.strip().lower()
    snapshot_gcs_base_url = settings.snapshot_gcs_base_url.strip()

    if settings.app_env == "production":
        if snapshot_source in {"", "local"}:
            snapshot_source = DEFAULT_PRODUCTION_SNAPSHOT_SOURCE
        if not snapshot_gcs_base_url:
            snapshot_gcs_base_url = DEFAULT_PRODUCTION_SNAPSHOT_GCS_BASE_URL

    return replace(
        settings,
        snapshot_source=snapshot_source,
        snapshot_gcs_base_url=snapshot_gcs_base_url,
    )


def get_settings() -> Settings:
    public_data_dir = Path(os.getenv("PUBLIC_DATA_DIR", str(DEFAULT_PUBLIC_DATA_DIR)))
    settings = Settings(
        app_env=os.getenv("APP_ENV", "development"),
        web_host=os.getenv("WEB_HOST", DEFAULT_WEB_HOST),
        web_port=_get_port(),
        session_secret_key=os.getenv("SESSION_SECRET_KEY", DEFAULT_SESSION_SECRET_KEY),
        public_data_dir=public_data_dir,
        publish_root_dir=Path(os.getenv("PUBLISH_ROOT_DIR", str(public_data_dir))),
        feedback_db_path=Path(os.getenv("FEEDBACK_DB_PATH", str(DEFAULT_FEEDBACK_DB_PATH))),
        app_db_path=Path(os.getenv("APP_DB_PATH", str(DEFAULT_APP_DB_PATH))),
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
        internal_preview_enabled=_get_bool(
            "INTERNAL_PREVIEW_ENABLED",
            DEFAULT_INTERNAL_PREVIEW_ENABLED,
        ),
        analytics_preview_allowed_emails=_get_csv_tuple(
            "ANALYTICS_PREVIEW_ALLOWED_EMAILS",
            DEFAULT_ANALYTICS_PREVIEW_ALLOWED_EMAILS,
        ),
        trial_mode=_get_bool("TRIAL_MODE", DEFAULT_TRIAL_MODE),
        trial_default_plan=os.getenv("TRIAL_DEFAULT_PLAN", DEFAULT_TRIAL_DEFAULT_PLAN),
        trial_end_date=os.getenv("TRIAL_END_DATE", DEFAULT_TRIAL_END_DATE),
        trial_applies_to=os.getenv("TRIAL_APPLIES_TO", DEFAULT_TRIAL_APPLIES_TO),
        allow_higher_plan_during_trial=_get_bool(
            "ALLOW_HIGHER_PLAN_DURING_TRIAL",
            DEFAULT_ALLOW_HIGHER_PLAN_DURING_TRIAL,
        ),
        billing_enabled=_get_bool("BILLING_ENABLED", DEFAULT_BILLING_ENABLED),
        billing_mode=os.getenv("BILLING_MODE", DEFAULT_BILLING_MODE),
        billing_cycle_days=int(os.getenv("BILLING_CYCLE_DAYS", str(DEFAULT_BILLING_CYCLE_DAYS))),
        billing_currency=os.getenv("BILLING_CURRENCY", DEFAULT_BILLING_CURRENCY),
        lightpay_mid=os.getenv("LIGHTPAY_MID", DEFAULT_LIGHTPAY_MID),
        lightpay_merchant_key=os.getenv(
            "LIGHTPAY_MERCHANT_KEY",
            DEFAULT_LIGHTPAY_MERCHANT_KEY,
        ),
        lightpay_return_url=os.getenv("LIGHTPAY_RETURN_URL", DEFAULT_LIGHTPAY_RETURN_URL),
        lightpay_notify_url=os.getenv("LIGHTPAY_NOTIFY_URL", DEFAULT_LIGHTPAY_NOTIFY_URL),
        lightpay_notify_allowed_ips=_get_csv_tuple(
            "LIGHTPAY_NOTIFY_ALLOWED_IPS",
            DEFAULT_LIGHTPAY_NOTIFY_ALLOWED_IPS,
        ),
        phone_verification_mode=os.getenv(
            "PHONE_VERIFICATION_MODE",
            DEFAULT_PHONE_VERIFICATION_MODE,
        ),
        phone_verification_code_ttl_seconds=int(
            os.getenv(
                "PHONE_VERIFICATION_CODE_TTL_SECONDS",
                str(DEFAULT_PHONE_VERIFICATION_CODE_TTL_SECONDS),
            )
        ),
        phone_verification_preview_enabled=_get_bool(
            "PHONE_VERIFICATION_PREVIEW_ENABLED",
            DEFAULT_PHONE_VERIFICATION_PREVIEW_ENABLED,
        ),
        login_email_verification_enabled=_get_bool(
            "LOGIN_EMAIL_VERIFICATION_ENABLED",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_ENABLED,
        ),
        login_email_verification_mode=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_MODE",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_MODE,
        )
        .strip()
        .lower(),
        login_email_verification_code_ttl_seconds=int(
            os.getenv(
                "LOGIN_EMAIL_VERIFICATION_CODE_TTL_SECONDS",
                str(DEFAULT_LOGIN_EMAIL_VERIFICATION_CODE_TTL_SECONDS),
            )
        ),
        login_email_verification_preview_enabled=_get_bool(
            "LOGIN_EMAIL_VERIFICATION_PREVIEW_ENABLED",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_PREVIEW_ENABLED,
        ),
        login_email_verification_smtp_host=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_SMTP_HOST",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_HOST,
        ).strip(),
        login_email_verification_smtp_port=int(
            os.getenv(
                "LOGIN_EMAIL_VERIFICATION_SMTP_PORT",
                str(DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PORT),
            )
        ),
        login_email_verification_smtp_ssl=_get_bool(
            "LOGIN_EMAIL_VERIFICATION_SMTP_SSL",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_SSL,
        ),
        login_email_verification_smtp_starttls=_get_bool(
            "LOGIN_EMAIL_VERIFICATION_SMTP_STARTTLS",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_STARTTLS,
        ),
        login_email_verification_smtp_username=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_SMTP_USERNAME",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_USERNAME,
        ).strip(),
        login_email_verification_smtp_password=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_SMTP_PASSWORD",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_PASSWORD,
        ),
        login_email_verification_from_email=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_FROM_EMAIL",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_EMAIL,
        ).strip(),
        login_email_verification_from_name=os.getenv(
            "LOGIN_EMAIL_VERIFICATION_FROM_NAME",
            DEFAULT_LOGIN_EMAIL_VERIFICATION_FROM_NAME,
        ).strip(),
        login_email_verification_smtp_timeout_seconds=int(
            os.getenv(
                "LOGIN_EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS",
                str(DEFAULT_LOGIN_EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS),
            )
        ),
        market_analysis_source=os.getenv(
            "MARKET_ANALYSIS_SOURCE",
            DEFAULT_MARKET_ANALYSIS_SOURCE,
        )
        .strip()
        .lower(),
        market_analysis_base_url=os.getenv(
            "MARKET_ANALYSIS_BASE_URL",
            DEFAULT_MARKET_ANALYSIS_BASE_URL,
        ).strip(),
        s2_holdings_csv=Path(os.getenv("S2_HOLDINGS_CSV", str(DEFAULT_S2_HOLDINGS_CSV))),
        s2_snapshot_csv=Path(os.getenv("S2_SNAPSHOT_CSV", str(DEFAULT_S2_SNAPSHOT_CSV))),
        s2_summary_csv=Path(os.getenv("S2_SUMMARY_CSV", str(DEFAULT_S2_SUMMARY_CSV))),
        user_snapshot_dir=Path(os.getenv("USER_SNAPSHOT_DIR", str(DEFAULT_USER_SNAPSHOT_DIR))),
        market_analysis_dir=Path(
            os.getenv("MARKET_ANALYSIS_DIR", str(DEFAULT_MARKET_ANALYSIS_DIR))
        ),
        tseries_operational_db_path=Path(
            os.getenv(
                "TSERIES_OPERATIONAL_DB_PATH",
                str(DEFAULT_TSERIES_OPERATIONAL_DB_PATH),
            )
        ),
        investment_storage_source=os.getenv(
            "INVESTMENT_STORAGE_SOURCE",
            DEFAULT_INVESTMENT_STORAGE_SOURCE,
        )
        .strip()
        .lower(),
        investment_gcs_bucket=os.getenv(
            "INVESTMENT_GCS_BUCKET",
            DEFAULT_INVESTMENT_GCS_BUCKET,
        ).strip(),
        investment_gcs_prefix=os.getenv(
            "INVESTMENT_GCS_PREFIX",
            DEFAULT_INVESTMENT_GCS_PREFIX,
        ).strip(),
        ui_redesign_enabled=_get_bool("UI_REDESIGN_ENABLED", DEFAULT_UI_REDESIGN_ENABLED),
        ui_theme_default=_get_theme_default(),
        investment_price_db_path=Path(
            os.getenv(
                "INVESTMENT_PRICE_DB_PATH",
                str(DEFAULT_INVESTMENT_PRICE_DB_PATH),
            )
        ),
        bootstrap_admin_email=os.getenv(
            "BOOTSTRAP_ADMIN_EMAIL",
            DEFAULT_BOOTSTRAP_ADMIN_EMAIL,
        ).strip(),
        bootstrap_admin_password=os.getenv(
            "BOOTSTRAP_ADMIN_PASSWORD",
            DEFAULT_BOOTSTRAP_ADMIN_PASSWORD,
        ),
    )
    return _normalize_snapshot_runtime(settings)
