from pathlib import Path

import pytest

from service_platform.feedback.storage import (
    FeedbackDuplicateError,
    FeedbackRateLimitError,
    FeedbackStore,
    FeedbackSubmission,
    FeedbackValidationError,
)
from service_platform.shared.config import Settings


def build_settings(tmp_path: Path) -> Settings:
    public_data_dir = tmp_path / "public_data"
    return Settings(
        app_env="test",
        web_host="127.0.0.1",
        web_port=8000,
        session_secret_key="test-secret",
        public_data_dir=public_data_dir,
        publish_root_dir=public_data_dir,
        feedback_db_path=tmp_path / "feedback.db",
        app_db_path=tmp_path / "app.db",
        backup_dir=tmp_path / "backups",
        alert_log_path=tmp_path / "alerts.log",
        alert_webhook_url="",
        alert_throttle_seconds=10,
        log_level="INFO",
        publish_keep_days=14,
        snapshot_source="local",
        snapshot_cache_ttl_seconds=60,
        snapshot_stale_after_hours=24,
        snapshot_gcs_bucket="",
        snapshot_gcs_base_url="",
        feedback_rate_limit_seconds=60,
        feedback_duplicate_window_seconds=3600,
        feedback_message_min_length=10,
        feedback_admin_key="secret-key",
        analytics_window_hours=24,
        trial_mode=True,
        trial_default_plan="starter",
        trial_end_date="2026-06-11",
        trial_applies_to="authenticated_only",
        allow_higher_plan_during_trial=True,
        billing_enabled=False,
        billing_mode="test",
        billing_cycle_days=30,
        billing_currency="KRW",
        lightpay_mid="test-mid",
        lightpay_merchant_key="test-merchant-key",
        lightpay_return_url="http://127.0.0.1:8000/billing/return",
        lightpay_notify_url="http://127.0.0.1:8000/billing/notify",
        lightpay_notify_allowed_ips=(),
        phone_verification_mode="mock",
        phone_verification_code_ttl_seconds=300,
        phone_verification_preview_enabled=True,
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
    )


def build_submission(**overrides) -> FeedbackSubmission:
    payload = {
        "email": "user@example.com",
        "message": "Need more detail on why the model likes these names.",
        "page": "/feedback",
        "consent": True,
        "user_agent": "pytest",
        "ip_address": "127.0.0.1",
    }
    payload.update(overrides)
    return FeedbackSubmission(**payload)


def test_feedback_store_accepts_valid_submission(tmp_path: Path) -> None:
    store = FeedbackStore(build_settings(tmp_path))

    result = store.submit_feedback(build_submission())
    rows = store.list_recent_feedback()
    metrics = store.get_metrics_summary()

    assert result["feedback_id"]
    assert rows[0]["email"] == "user@example.com"
    assert metrics["feedback_submissions"] == 1


def test_feedback_store_rejects_invalid_message_rate_limit_and_duplicate(
    tmp_path: Path,
) -> None:
    store = FeedbackStore(build_settings(tmp_path))

    with pytest.raises(FeedbackValidationError):
        store.submit_feedback(build_submission(message="too short"))

    store.submit_feedback(build_submission())

    with pytest.raises(FeedbackRateLimitError):
        store.submit_feedback(build_submission(ip_address="127.0.0.1", email="other@example.com"))

    with pytest.raises(FeedbackDuplicateError):
        store.submit_feedback(build_submission(ip_address="10.0.0.2"))


def test_feedback_store_records_metrics_events(tmp_path: Path) -> None:
    store = FeedbackStore(build_settings(tmp_path))

    store.record_event(event_name="page_view", page="/today")
    store.record_event(event_name="page_view", page="/today")
    store.record_event(event_name="ticker_click", page="/today", ticker="005930")
    store.record_event(
        event_name="model_section_view",
        page="/today",
        model_id="s2_regime_growth",
    )

    metrics = store.get_metrics_summary()

    assert metrics["page_views"] == 2
    assert metrics["today_page_views"] == 2
    assert metrics["ticker_clicks"][0]["ticker"] == "005930"
    assert metrics["model_interest"][0]["model_id"] == "s2_regime_growth"
