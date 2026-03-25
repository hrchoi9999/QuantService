"""Project-wide constants for the service platform."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PUBLIC_DATA_DIR = PROJECT_ROOT / "service_platform" / "web" / "public_data"
DEFAULT_FEEDBACK_DB_PATH = PROJECT_ROOT / "data" / "feedback.db"
DEFAULT_APP_DB_PATH = PROJECT_ROOT / "data" / "app.db"
DEFAULT_ALERT_LOG_PATH = PROJECT_ROOT / "data" / "alerts.log"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8000
DEFAULT_SESSION_SECRET_KEY = "change-me-in-production"
DEFAULT_PUBLISH_KEEP_DAYS = 14
DEFAULT_SNAPSHOT_SOURCE = "local"
DEFAULT_SNAPSHOT_CACHE_TTL_SECONDS = 60
DEFAULT_SNAPSHOT_STALE_AFTER_HOURS = 24
DEFAULT_SNAPSHOT_GCS_BUCKET = ""
DEFAULT_SNAPSHOT_GCS_BASE_URL = ""
DEFAULT_MARKET_ANALYSIS_SOURCE = "local"
DEFAULT_MARKET_ANALYSIS_BASE_URL = ""
DEFAULT_ANALYTICS_PREVIEW_ALLOWED_EMAILS = ""
DEFAULT_BOOTSTRAP_ADMIN_EMAIL = ""
DEFAULT_BOOTSTRAP_ADMIN_PASSWORD = ""
DEFAULT_FEEDBACK_RATE_LIMIT_SECONDS = 60
DEFAULT_FEEDBACK_DUPLICATE_WINDOW_SECONDS = 3600
DEFAULT_FEEDBACK_MESSAGE_MIN_LENGTH = 10
DEFAULT_FEEDBACK_ADMIN_KEY = ""
DEFAULT_ANALYTICS_WINDOW_HOURS = 24
DEFAULT_ALERT_WEBHOOK_URL = ""
DEFAULT_ALERT_THROTTLE_SECONDS = 1800
DEFAULT_TRIAL_MODE = True
DEFAULT_TRIAL_DEFAULT_PLAN = "starter"
DEFAULT_TRIAL_END_DATE = ""
DEFAULT_TRIAL_APPLIES_TO = "authenticated_only"
DEFAULT_ALLOW_HIGHER_PLAN_DURING_TRIAL = True
DEFAULT_BILLING_ENABLED = False
DEFAULT_BILLING_MODE = "test"
DEFAULT_BILLING_CYCLE_DAYS = 30
DEFAULT_BILLING_CURRENCY = "KRW"
DEFAULT_LIGHTPAY_MID = ""
DEFAULT_LIGHTPAY_MERCHANT_KEY = ""
DEFAULT_LIGHTPAY_RETURN_URL = "http://127.0.0.1:8000/billing/return"
DEFAULT_LIGHTPAY_NOTIFY_URL = "http://127.0.0.1:8000/billing/notify"
DEFAULT_LIGHTPAY_NOTIFY_ALLOWED_IPS = ""
DEFAULT_PHONE_VERIFICATION_MODE = "mock"
DEFAULT_PHONE_VERIFICATION_CODE_TTL_SECONDS = 300
DEFAULT_PHONE_VERIFICATION_PREVIEW_ENABLED = True
DEFAULT_USER_SNAPSHOT_DIR = Path(r"D:\Quant\service_platform\web\public_data\current")
DEFAULT_MARKET_ANALYSIS_DIR = (
    PROJECT_ROOT / "service_platform" / "web" / "public_data" / "market_analysis" / "current"
)
CURRENT_DIRNAME = "current"
PUBLISHED_DIRNAME = "published"
TMP_DIRNAME = "tmp"
LOG_DIRNAME = "logs"
MANIFEST_FILENAME = "publish_manifest.json"
SNAPSHOT_FILENAMES = {
    "model_catalog": "model_catalog.json",
    "daily_recommendations": "daily_recommendations.json",
    "recent_changes": "recent_changes.json",
    "performance_summary": "performance_summary.json",
}
DEFAULT_S2_HOLDINGS_CSV = (
    PROJECT_ROOT
    / "quant_models"
    / "Quant"
    / "src"
    / "backtest"
    / "outputs"
    / "backtest_regime"
    / "regime_bt_holdings_3m_S2_RBW_top30_GR43_SMA140_MG1_EX2_20131014_20260206.csv"
)
DEFAULT_S2_SNAPSHOT_CSV = (
    PROJECT_ROOT
    / "quant_models"
    / "Quant"
    / "src"
    / "backtest"
    / "outputs"
    / "backtest_regime"
    / "regime_bt_snapshot_3m_S2_RBW_top30_GR43_SMA140_MG1_EX2_20131014_20260206.csv"
)
DEFAULT_S2_SUMMARY_CSV = (
    PROJECT_ROOT
    / "quant_models"
    / "Quant"
    / "src"
    / "backtest"
    / "outputs"
    / "backtest_regime"
    / "regime_bt_summary_3m_S2_RBW_top30_GR43_SMA140_MG1_EX2_20131014_20260206.csv"
)
