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


def test_plan_entitlement_update_changes_matrix(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    store.update_plan_entitlement(
        plan_id="starter",
        entitlement_key="recommendation_n_per_model",
        value_json="15",
    )

    entitlements = store.get_plan_entitlements("starter")
    assert entitlements["recommendation_n_per_model"] == 15


def test_audit_log_records_admin_actions(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))
    admin = store.authenticate_or_register("admin@example.com", "pass1234")

    store.record_audit_log(
        admin_user_id=admin.id,
        action_type="admin.test.action",
        target_type="user",
        target_id="member@example.com",
        payload_summary='{"email":"member@example.com"}',
        result="success",
        ip_address="127.0.0.1",
    )

    rows = store.list_recent_audit_logs(limit=5)
    assert rows[0]["action_type"] == "admin.test.action"
    assert rows[0]["admin_email"] == "admin@example.com"


def test_register_local_user_stores_verified_phone_profile(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    user = store.register_local_user(
        email="member@naver.com",
        password="pass1234",
        phone_number="010-1234-5678",
    )
    profile = store.get_user_profile(user.id)

    assert profile["auth_provider"] == "local"
    assert profile["phone_number"] == "01012345678"
    assert profile["phone_verification_status"] == "verified"


def test_get_user_profile_creates_unverified_profile_without_promoting_state(
    tmp_path: Path,
) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    user = store.authenticate_or_register("member@example.com", "pass1234")
    profile = store.get_user_profile(user.id)

    assert profile["auth_provider"] == "local"
    assert profile["phone_number"] is None
    assert profile["phone_verification_status"] == "unverified"
    assert profile["phone_verified_at"] is None


def test_get_user_profile_keeps_verified_state_for_existing_profile(tmp_path: Path) -> None:
    store = AccessStore(build_settings(tmp_path, trial_mode=False))

    user = store.register_local_user(
        email="verified@naver.com",
        password="pass1234",
        phone_number="010-9876-5432",
    )
    profile = store.get_user_profile(user.id)

    assert profile["phone_verification_status"] == "verified"
    assert profile["phone_verified_at"] is not None
