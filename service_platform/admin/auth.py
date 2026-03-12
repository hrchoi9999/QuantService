from __future__ import annotations

from dataclasses import dataclass

from flask import Request

from service_platform.feedback.handlers import is_admin_request
from service_platform.shared.config import Settings


@dataclass(frozen=True)
class PolicyState:
    phase_label: str
    phase_code: str
    summary: str


def get_policy_state(settings: Settings) -> PolicyState:
    if settings.billing_enabled:
        return PolicyState(
            phase_label="2단계 유료화 이후",
            phase_code="phase_2_paid",
            summary="구독과 결제가 활성화된 운영 단계입니다.",
        )
    return PolicyState(
        phase_label="1단계 무료기간",
        phase_code="phase_1_trial",
        summary="결제는 닫혀 있고, 로그인 회원은 trial 정책이 적용됩니다.",
    )


def require_admin(request: Request, settings: Settings, access_context) -> bool:
    return is_admin_request(request, settings, access_context)
