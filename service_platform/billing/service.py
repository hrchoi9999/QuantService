from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import randint

from service_platform.access.store import AccessStore
from service_platform.billing.lightpay import (
    ALLOWED_PAY_METHODS,
    BILLING_PLAN_PRICES,
    LightPayClient,
    LightPayValidationError,
)
from service_platform.shared.config import Settings


class BillingDisabledError(RuntimeError):
    pass


@dataclass(frozen=True)
class BillingResult:
    status: str
    message: str
    ord_no: str | None = None
    plan_id: str | None = None
    duplicate: bool = False


class BillingService:
    def __init__(
        self,
        settings: Settings,
        access_store: AccessStore,
        approval_requester=None,
    ) -> None:
        self.settings = settings
        self.access_store = access_store
        self.lightpay = LightPayClient(settings)
        self.approval_requester = approval_requester

    def list_paid_plans(self) -> list[dict[str, object]]:
        plan_rows = []
        for plan in self.access_store.list_plans():
            plan_id = plan["plan_id"]
            if plan_id == "free":
                continue
            plan_rows.append(
                {
                    **plan,
                    "amount": BILLING_PLAN_PRICES[plan_id],
                    "allowed_methods": self.allowed_pay_methods,
                }
            )
        return plan_rows

    @property
    def allowed_pay_methods(self) -> tuple[str, ...]:
        return ALLOWED_PAY_METHODS

    def create_checkout(
        self,
        *,
        user_id: int,
        user_email: str,
        plan_id: str,
        pay_method: str,
    ):
        self._ensure_enabled()
        amount = self._plan_amount(plan_id)
        self.lightpay.validate_pay_method(pay_method)
        ord_no = self._generate_ord_no(user_id)
        self.access_store.create_order(
            ord_no=ord_no,
            user_id=user_id,
            plan_id=plan_id,
            amount=amount,
            currency=self.settings.billing_currency,
            pay_method_requested=pay_method,
        )
        form = self.lightpay.build_checkout_form(
            ord_no=ord_no,
            plan_id=plan_id,
            amount=amount,
            pay_method=pay_method,
            user_email=user_email,
        )
        self.access_store.update_order_status(ord_no=ord_no, status="redirected")
        return form, ord_no

    def handle_return(self, payload: dict[str, str]) -> BillingResult:
        self._ensure_enabled()
        ord_no = payload.get("ordNo", "")
        order = self.access_store.get_order_by_ord_no(ord_no)
        if order is None:
            return BillingResult(status="error", message="주문 정보를 찾을 수 없습니다.")

        inserted = self.access_store.record_payment_event(
            provider="lightpay",
            event_type="return",
            ord_no=ord_no,
            tid=payload.get("tid", ""),
            mid=payload.get("mid", self.settings.lightpay_mid),
            result_cd=payload.get("resultCd", ""),
            result_msg=payload.get("resultMsg", ""),
            pm_cd=payload.get("pmCd", ""),
            goods_amt=payload.get("goodsAmt", ""),
            edi_date=payload.get("ediDate", ""),
            raw_payload=payload,
            idempotency_key=f"return:{payload.get('tid', '')}:{ord_no}",
        )
        if not inserted:
            return BillingResult(
                status="duplicate",
                message="이미 처리된 결제 복귀 요청입니다.",
                ord_no=ord_no,
                duplicate=True,
            )

        if payload.get("resultCd") != "0000":
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(
                status="failed",
                message=payload.get("resultMsg", "결제가 실패했습니다."),
                ord_no=ord_no,
            )

        try:
            self.lightpay.verify_signature(payload)
            self.lightpay.validate_pm_code(payload.get("pmCd", ""))
            approval_result = self.lightpay.approve(
                payload,
                approval_requester=self.approval_requester,
            )
        except LightPayValidationError as exc:
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(status="failed", message=str(exc), ord_no=ord_no)

        approval_tid = approval_result.get("tid", payload.get("tid", ""))
        self.access_store.record_payment_event(
            provider="lightpay",
            event_type="approval",
            ord_no=ord_no,
            tid=approval_tid,
            mid=approval_result.get("mid", self.settings.lightpay_mid),
            result_cd=approval_result.get("resultCd", ""),
            result_msg=approval_result.get("resultMsg", ""),
            pm_cd=approval_result.get("pmCd", payload.get("pmCd", "")),
            goods_amt=approval_result.get("goodsAmt", payload.get("goodsAmt", "")),
            edi_date=approval_result.get("ediDate", payload.get("ediDate", "")),
            raw_payload=approval_result,
            idempotency_key=f"approval:{approval_tid}:{ord_no}",
        )
        if approval_result.get("resultCd") != "0000":
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(
                status="failed",
                message=approval_result.get("resultMsg", "결제 승인에 실패했습니다."),
                ord_no=ord_no,
            )

        return self._finalize_success(
            ord_no=ord_no,
            order=order,
            payload=approval_result,
            fallback_pm_cd=payload.get("pmCd", ""),
        )

    def handle_notify(self, payload: dict[str, str]) -> BillingResult:
        self._ensure_enabled()
        ord_no = payload.get("ordNo", "")
        order = self.access_store.get_order_by_ord_no(ord_no)
        if order is None:
            return BillingResult(
                status="ignored",
                message="알 수 없는 주문입니다.",
                ord_no=ord_no,
            )

        inserted = self.access_store.record_payment_event(
            provider="lightpay",
            event_type="notify",
            ord_no=ord_no,
            tid=payload.get("tid", ""),
            mid=payload.get("mid", self.settings.lightpay_mid),
            result_cd=payload.get("resultCd", ""),
            result_msg=payload.get("resultMsg", ""),
            pm_cd=payload.get("pmCd", ""),
            goods_amt=payload.get("goodsAmt", ""),
            edi_date=payload.get("ediDate", ""),
            raw_payload=payload,
            idempotency_key=f"notify:{payload.get('tid', '')}:{ord_no}",
        )
        if not inserted:
            return BillingResult(
                status="duplicate",
                message="중복 결제 통보입니다.",
                ord_no=ord_no,
                duplicate=True,
            )

        try:
            self.lightpay.verify_signature(payload)
            self.lightpay.validate_pm_code(payload.get("pmCd", ""))
        except LightPayValidationError as exc:
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(status="failed", message=str(exc), ord_no=ord_no)

        if payload.get("resultCd") != "0000":
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(
                status="failed",
                message=payload.get("resultMsg", "결제 통보 실패"),
                ord_no=ord_no,
            )

        return self._finalize_success(
            ord_no=ord_no,
            order=order,
            payload=payload,
            fallback_pm_cd=payload.get("pmCd", ""),
        )

    def _finalize_success(
        self,
        *,
        ord_no: str,
        order: dict[str, object],
        payload: dict[str, str],
        fallback_pm_cd: str,
    ) -> BillingResult:
        try:
            self.lightpay.validate_pm_code(payload.get("pmCd", fallback_pm_cd))
        except LightPayValidationError as exc:
            self.access_store.update_order_status(ord_no=ord_no, status="failed")
            return BillingResult(status="failed", message=str(exc), ord_no=ord_no)

        self.access_store.update_order_status(ord_no=ord_no, status="approved")
        started_at = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = started_at + timedelta(days=self.settings.billing_cycle_days)
        self.access_store.activate_subscription_from_payment(
            user_id=int(order["user_id"]),
            plan_id=str(order["plan_id"]),
            started_at=started_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        return BillingResult(
            status="approved",
            message="결제가 승인되었습니다.",
            ord_no=ord_no,
            plan_id=str(order["plan_id"]),
        )

    def _generate_ord_no(self, user_id: int) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"RB-{stamp}-{user_id}-{randint(1000, 9999)}"

    def _plan_amount(self, plan_id: str) -> int:
        if plan_id not in BILLING_PLAN_PRICES:
            raise LightPayValidationError("결제 가능한 플랜이 아닙니다.")
        return BILLING_PLAN_PRICES[plan_id]

    def _ensure_enabled(self) -> None:
        if not self.settings.billing_enabled:
            raise BillingDisabledError("결제 기능이 비활성화되어 있습니다.")
