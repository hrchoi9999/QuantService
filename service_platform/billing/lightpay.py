from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

ALLOWED_PAY_METHODS = ("CARD", "MOBILE", "KAKAOPAY", "NPAY", "TOSSPAY", "PAYCO")
BLOCKED_PAY_METHODS = ("TRANS", "VACNT", "MYACCOUNT")
ALLOWED_PM_CODES = {"01", "05", "20", "21", "24", "25"}
BLOCKED_PM_CODES = {"02", "03", "23"}
BILLING_PLAN_PRICES = {
    "starter": 9900,
    "pro": 19900,
    "premium": 29900,
}


class LightPayValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CheckoutForm:
    action_url: str
    fields: dict[str, str]


class LightPayClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def view_request_url(self) -> str:
        if self.settings.billing_mode == "prod":
            return "https://paywin.lightpay.kr/payment/v1/view/request"
        return "https://testpaywin.lightpay.kr/payment/v1/view/request"

    def build_checkout_form(
        self,
        *,
        ord_no: str,
        plan_id: str,
        amount: int,
        pay_method: str,
        user_email: str,
    ) -> CheckoutForm:
        self.validate_pay_method(pay_method)
        edi_date = self._edi_date()
        fields = {
            "mid": self.settings.lightpay_mid,
            "ordNo": ord_no,
            "goodsNm": f"redbot {plan_id}",
            "goodsAmt": str(amount),
            "currency": self.settings.billing_currency,
            "payMethod": pay_method,
            "buyerEmail": user_email,
            "returnUrl": self.settings.lightpay_return_url,
            "notifyUrl": self.settings.lightpay_notify_url,
            "ediDate": edi_date,
            "hashString": self.make_request_hash(edi_date=edi_date, goods_amt=str(amount)),
        }
        return CheckoutForm(action_url=self.view_request_url, fields=fields)

    def validate_pay_method(self, pay_method: str) -> None:
        if pay_method in BLOCKED_PAY_METHODS or pay_method not in ALLOWED_PAY_METHODS:
            raise LightPayValidationError("허용되지 않은 결제수단입니다.")

    def validate_pm_code(self, pm_code: str) -> None:
        if pm_code in BLOCKED_PM_CODES or pm_code not in ALLOWED_PM_CODES:
            raise LightPayValidationError("허용되지 않은 결제 승인 수단입니다.")

    def make_request_hash(self, *, edi_date: str, goods_amt: str) -> str:
        return self._sha256(
            f"{self.settings.lightpay_mid}{edi_date}{goods_amt}{self.settings.lightpay_merchant_key}"
        )

    def make_signature(
        self,
        *,
        tid: str,
        edi_date: str,
        goods_amt: str,
        ord_no: str,
    ) -> str:
        return self._sha256(
            "".join(
                [
                    tid,
                    self.settings.lightpay_mid,
                    edi_date,
                    goods_amt,
                    ord_no,
                    self.settings.lightpay_merchant_key,
                ]
            )
        )

    def verify_signature(self, payload: dict[str, str]) -> None:
        sign_data = payload.get("signData") or payload.get("mSignData")
        if not sign_data:
            raise LightPayValidationError("서명 정보가 없습니다.")
        expected = self.make_signature(
            tid=payload.get("tid", ""),
            edi_date=payload.get("ediDate", ""),
            goods_amt=payload.get("goodsAmt", ""),
            ord_no=payload.get("ordNo", ""),
        )
        if sign_data != expected:
            raise LightPayValidationError("결제 응답 서명 검증에 실패했습니다.")

    def approve(
        self,
        payload: dict[str, str],
        approval_requester=None,
    ) -> dict[str, str]:
        approval_url = payload.get("approvalUrl", "")
        if not approval_url:
            raise LightPayValidationError("approvalUrl 이 없습니다.")
        edi_date = self._edi_date()
        request_payload = {
            "mid": self.settings.lightpay_mid,
            "tid": payload.get("tid", ""),
            "ordNo": payload.get("ordNo", ""),
            "goodsAmt": payload.get("goodsAmt", ""),
            "ediDate": edi_date,
            "payData": payload.get("payData", ""),
            "hashString": self.make_request_hash(
                edi_date=edi_date,
                goods_amt=payload.get("goodsAmt", ""),
            ),
        }
        if approval_requester is not None:
            return approval_requester(approval_url, request_payload)
        return self._default_approval_request(approval_url, request_payload)

    def _default_approval_request(
        self,
        approval_url: str,
        request_payload: dict[str, str],
    ) -> dict[str, str]:
        request = Request(
            approval_url,
            data=urlencode(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
        try:
            parsed = json.loads(body)
            return {str(key): str(value) for key, value in parsed.items()}
        except json.JSONDecodeError:
            raise LightPayValidationError("승인 응답을 해석하지 못했습니다.")

    def _edi_date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    def _sha256(self, raw_value: str) -> str:
        return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
