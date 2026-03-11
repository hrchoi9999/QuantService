from pathlib import Path

import pytest

from service_platform.access.store import AccessStore
from service_platform.billing.lightpay import LightPayValidationError
from service_platform.billing.service import BillingService
from service_platform.shared.config import Settings


def build_settings(tmp_path: Path, *, billing_enabled: bool = True) -> Settings:
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
        trial_mode=False,
        trial_default_plan="starter",
        trial_end_date="2026-06-11",
        trial_applies_to="authenticated_only",
        allow_higher_plan_during_trial=True,
        billing_enabled=billing_enabled,
        billing_mode="test",
        billing_cycle_days=30,
        billing_currency="KRW",
        lightpay_mid="test-mid",
        lightpay_merchant_key="test-merchant-key",
        lightpay_return_url="http://127.0.0.1:8000/billing/return",
        lightpay_notify_url="http://127.0.0.1:8000/billing/notify",
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
    )


def build_service(tmp_path: Path) -> tuple[BillingService, AccessStore, dict[str, object]]:
    settings = build_settings(tmp_path)
    access_store = AccessStore(settings)
    user = access_store.authenticate_or_register("member@example.com", "pass1234")

    def approval_requester(url: str, payload: dict[str, str]) -> dict[str, str]:
        return {
            "resultCd": "0000",
            "resultMsg": "APPROVED",
            "tid": payload["tid"],
            "mid": payload["mid"],
            "pmCd": "01",
            "goodsAmt": payload["goodsAmt"],
            "ediDate": payload["ediDate"],
            "ordNo": payload["ordNo"],
        }

    service = BillingService(settings, access_store, approval_requester=approval_requester)
    return service, access_store, {"id": user.id, "email": user.email}


def build_signed_payload(
    service: BillingService,
    *,
    ord_no: str,
    amount: int,
    pm_cd: str = "01",
    result_cd: str = "0000",
) -> dict[str, str]:
    payload = {
        "resultCd": result_cd,
        "resultMsg": "OK" if result_cd == "0000" else "DECLINED",
        "tid": "T202603110001",
        "mid": service.settings.lightpay_mid,
        "ediDate": "20260311123030",
        "goodsAmt": str(amount),
        "ordNo": ord_no,
        "pmCd": pm_cd,
        "approvalUrl": "https://approval.test/confirm",
        "payData": "encoded-data",
    }
    payload["signData"] = service.lightpay.make_signature(
        tid=payload["tid"],
        edi_date=payload["ediDate"],
        goods_amt=payload["goodsAmt"],
        ord_no=payload["ordNo"],
    )
    return payload


def test_billing_return_success_updates_subscription(tmp_path: Path) -> None:
    service, access_store, user = build_service(tmp_path)
    form, ord_no = service.create_checkout(
        user_id=int(user["id"]),
        user_email=str(user["email"]),
        plan_id="pro",
        pay_method="CARD",
    )

    payload = build_signed_payload(service, ord_no=ord_no, amount=int(form.fields["goodsAmt"]))
    result = service.handle_return(payload)
    access = access_store.get_effective_access(int(user["id"]))
    order = access_store.get_order_by_ord_no(ord_no)

    assert result.status == "approved"
    assert order is not None
    assert order["status"] == "approved"
    assert access.base_plan_id == "pro"
    assert access.effective_plan_id == "pro"
    assert access_store.count_payment_events(ord_no=ord_no, event_type="return") == 1
    assert access_store.count_payment_events(ord_no=ord_no, event_type="approval") == 1


def test_billing_return_failure_marks_order_failed(tmp_path: Path) -> None:
    service, access_store, user = build_service(tmp_path)
    form, ord_no = service.create_checkout(
        user_id=int(user["id"]),
        user_email=str(user["email"]),
        plan_id="starter",
        pay_method="CARD",
    )

    payload = build_signed_payload(
        service,
        ord_no=ord_no,
        amount=int(form.fields["goodsAmt"]),
        result_cd="9999",
    )
    result = service.handle_return(payload)
    order = access_store.get_order_by_ord_no(ord_no)

    assert result.status == "failed"
    assert order is not None
    assert order["status"] == "failed"


def test_duplicate_notify_is_idempotent(tmp_path: Path) -> None:
    service, access_store, user = build_service(tmp_path)
    form, ord_no = service.create_checkout(
        user_id=int(user["id"]),
        user_email=str(user["email"]),
        plan_id="premium",
        pay_method="KAKAOPAY",
    )

    payload = build_signed_payload(
        service,
        ord_no=ord_no,
        amount=int(form.fields["goodsAmt"]),
        pm_cd="20",
    )
    first = service.handle_notify(payload)
    second = service.handle_notify(payload)

    assert first.status == "approved"
    assert second.status == "duplicate"
    assert second.duplicate is True
    assert access_store.count_payment_events(ord_no=ord_no, event_type="notify") == 1


def test_forbidden_pay_method_is_blocked(tmp_path: Path) -> None:
    service, _, user = build_service(tmp_path)

    with pytest.raises(LightPayValidationError):
        service.create_checkout(
            user_id=int(user["id"]),
            user_email=str(user["email"]),
            plan_id="starter",
            pay_method="TRANS",
        )


def test_forbidden_pm_code_is_blocked(tmp_path: Path) -> None:
    service, access_store, user = build_service(tmp_path)
    form, ord_no = service.create_checkout(
        user_id=int(user["id"]),
        user_email=str(user["email"]),
        plan_id="starter",
        pay_method="CARD",
    )

    payload = build_signed_payload(
        service,
        ord_no=ord_no,
        amount=int(form.fields["goodsAmt"]),
        pm_cd="23",
    )
    result = service.handle_notify(payload)
    order = access_store.get_order_by_ord_no(ord_no)

    assert result.status == "failed"
    assert order is not None
    assert order["status"] == "failed"
