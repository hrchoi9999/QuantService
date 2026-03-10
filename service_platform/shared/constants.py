"""Project-wide constants for the service platform."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PUBLIC_DATA_DIR = PROJECT_ROOT / "service_platform" / "web" / "public_data"
DEFAULT_FEEDBACK_DB_PATH = PROJECT_ROOT / "data" / "feedback.db"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8000
