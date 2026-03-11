from datetime import date
from pathlib import Path

from service_platform.access.store import AccessStore
from service_platform.shared.config import Settings


def build_settings(
    tmp_path: Path,
    *,
    trial_mode: bool = True,
    trial_end_date: str = "2026-06-11",
    allow_higher: bool = True,
) -> Settings:
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
        alert_throttle_seconds=0,
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
        trial_mode=trial_mode,
        trial_default_plan="starter",
        trial_end_date=trial_end_date,
        trial_applies_to="authenticated_only",
        allow_higher_plan_during_trial=allow_higher,
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
    )


def test_trial_promotes_authenticated_user_to_starter(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=True))

    user = store.authenticate_or_register("member@example.com", "pass1234")
    access = store.get_effective_access(user.id, today=date(2026, 3, 11))

    assert access.base_plan_id == "free"
    assert access.effective_plan_id == "starter"
    assert access.entitlements["recommendation_sort_order"] == "top"
    assert access.entitlements["recommendation_n_per_model"] == 10


def test_subscription_plan_applies_when_trial_mode_is_off(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    user = store.authenticate_or_register("member@example.com", "pass1234")
    store.grant_plan(email=user.email, plan_id="pro", expires_at="2026-12-31")
    access = store.get_effective_access(user.id, today=date(2026, 3, 11))

    assert access.base_plan_id == "pro"
    assert access.effective_plan_id == "pro"
    assert access.entitlements["recommendation_n_per_model"] == 20


def test_trial_can_preserve_higher_paid_plan_when_enabled(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=True, allow_higher=True))

    user = store.authenticate_or_register("pro@example.com", "pass1234")
    store.grant_plan(email=user.email, plan_id="premium", expires_at="2026-12-31")
    access = store.get_effective_access(user.id, today=date(2026, 3, 11))

    assert access.base_plan_id == "premium"
    assert access.effective_plan_id == "premium"


def test_admin_role_marks_access_context_as_admin(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    user = store.authenticate_or_register("admin@example.com", "pass1234")
    store.assign_role(email=user.email)
    access = store.get_effective_access(user.id, today=date(2026, 3, 11))

    assert access.is_admin is True
    assert "admin" in access.roles
