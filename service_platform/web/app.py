from __future__ import annotations

import json
import secrets
import shutil
from datetime import datetime, timedelta
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from service_platform.access.store import (
    AccessContext,
    AccessStore,
    AdminValidationError,
    GrantValidationError,
    LoginValidationError,
    RegistrationValidationError,
)
from service_platform.admin.auth import get_policy_state, require_admin
from service_platform.billing import BillingDisabledError, BillingService, LightPayValidationError
from service_platform.feedback.handlers import (
    build_feedback_redirect,
    build_feedback_submission,
)
from service_platform.feedback.storage import (
    FeedbackDuplicateError,
    FeedbackRateLimitError,
    FeedbackStore,
    FeedbackValidationError,
)
from service_platform.shared.config import Settings, get_settings
from service_platform.shared.constants import CURRENT_DIRNAME, MANIFEST_FILENAME, PUBLISHED_DIRNAME
from service_platform.shared.logging import configure_logging
from service_platform.shared.notifications import send_alert
from service_platform.web.analytics_preview_api import (
    AnalyticsPreviewApi,
    AnalyticsPreviewLoadError,
)
from service_platform.web.analytics_preview_p2_api import (
    AnalyticsPreviewP2Api,
    AnalyticsPreviewP2LoadError,
)
from service_platform.web.data_provider import SnapshotDataProvider, SnapshotLoadError
from service_platform.web.market_analysis_api import MarketAnalysisLoadError, MarketAnalysisMockApi
from service_platform.web.user_snapshot_api import UserSnapshotLoadError, UserSnapshotMockApi

STATUS_MESSAGES = {
    "invalid": "이메일 또는 비밀번호를 다시 확인해 주세요.",
    "signup_success": "회원가입이 완료되었습니다. 로그인해 주세요.",
    "code_sent": "휴대폰 인증번호를 발급했습니다.",
    "verify_required": "휴대폰 인증을 먼저 완료해 주세요.",
    "email_exists": "이미 가입된 이메일입니다. 로그인해 주세요.",
    "code_invalid": "인증번호를 다시 확인해 주세요.",
    "logged_out": "로그아웃되었습니다.",
    "granted": "플랜이 적용되었습니다.",
    "revoked": "플랜이 회수되었습니다.",
    "updated": "설정이 반영되었습니다.",
    "refreshed": "캐시를 새로 고쳤습니다.",
    "activated": "선택한 스냅샷을 current로 반영했습니다.",
    "locked": "사용자를 잠금 처리했습니다.",
    "unlocked": "사용자 잠금을 해제했습니다.",
    "error": "요청을 처리하지 못했습니다. 입력값을 다시 확인해 주세요.",
}
BILLING_MESSAGES = {
    "disabled": "현재 결제 기능은 비활성화되어 있습니다.",
    "login_required": "결제를 진행하려면 먼저 로그인해 주세요.",
    "invalid": "결제 요청을 처리하지 못했습니다. 결제수단과 플랜을 다시 확인해 주세요.",
}
PUBLIC_NOTICE_BLOCKS = {
    "service_nature": {
        "title": "서비스 성격 안내",
        "body": (
            "Redbot은 불특정 다수에게 동일한 공개형 모델 정보와 시장 브리핑을 제공하는 "
            "서비스입니다."
        ),
    },
    "non_advice": {
        "title": "개별 상담 불가 안내",
        "body": (
            "본 서비스는 특정 이용자의 투자목적, 재산상황, 손실감수성 등을 반영한 "
            "개별 투자자문을 제공하지 않습니다."
        ),
    },
    "risk": {
        "title": "투자위험 안내",
        "body": (
            "모든 투자에는 원금손실 위험이 있으며, 투자판단과 책임은 이용자 본인에게 " "있습니다."
        ),
    },
    "backtest": {
        "title": "백테스트 안내",
        "body": (
            "표시된 성과지표는 실제 투자계좌 성과가 아닌 백테스트 결과이며, 과거 성과는 "
            "미래 수익을 보장하지 않습니다."
        ),
    },
    "market_brief": {
        "title": "시장 브리핑 안내",
        "body": (
            "시장 브리핑은 공개된 시장 데이터를 해석한 참고 정보이며, 특정 매매행동을 "
            "안내하는 자료가 아닙니다."
        ),
    },
}


def _format_datetime(value: str | None) -> str:
    if not value:
        return "-"
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M KST")


def _format_kst_datetime(value: str | None) -> str:
    if not value:
        return "-"
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M KST")


def _format_percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _ticker_target_url(ticker: str) -> str:
    return f"https://finance.naver.com/item/main.naver?code={ticker}"


def _safe_next_url(candidate: str | None) -> str:
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for("today")


def _request_ip_address() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _build_public_model_compliance_note(bundle: Any) -> str:
    default_note = (
        "이 화면은 다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보를 설명하는 참고자료이며 "
        "특정 개인에 대한 투자자문이나 실제 매매 지시가 아닙니다."
    )
    reports = bundle.recommendation_today.get("reports", []) if bundle else []
    for report in reports:
        disclaimer = str(report.get("disclaimer_text") or "").strip()
        if disclaimer:
            return disclaimer
    return default_note


def _build_notice_blocks(*keys: str) -> list[dict[str, str]]:
    return [PUBLIC_NOTICE_BLOCKS[key] for key in keys if key in PUBLIC_NOTICE_BLOCKS]


def _is_notify_ip_allowed(settings: Settings) -> bool:
    if not settings.lightpay_notify_allowed_ips:
        return True
    return _request_ip_address() in settings.lightpay_notify_allowed_ips


PERIOD_DISPLAY_ORDER = {
    "1Y": 0,
    "2Y": 1,
    "3Y": 2,
    "6M": 3,
    "3M": 4,
    "5Y": 5,
    "FULL": 6,
}
REFERENCE_PERIODS = {"5Y", "FULL"}
RETURN_PERIODS = {"3M", "6M"}


def _allocation_bucket(item: dict[str, Any]) -> str:
    asset_group = str(item.get("asset_group") or "").lower()
    source_type = str(item.get("source_type") or "").lower()
    security_code = item.get("security_code")
    display_name = str(item.get("display_name") or "").lower()
    if (
        asset_group == "cash"
        or source_type == "cash"
        or (
            security_code in (None, "")
            and any(token in display_name for token in ("현금", "대기자금", "cash"))
        )
    ):
        return "cash"
    if asset_group == "stock" or source_type == "stock":
        return "stock"
    return "etf"


def _normalize_allocation_items(allocation_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in allocation_items:
        weight = float(item.get("target_weight") or 0)
        if abs(weight) < 1e-9:
            continue
        bucket = _allocation_bucket(item)
        security_code = str(item.get("security_code") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        key = (bucket, security_code, display_name)
        if bucket == "cash":
            key = (bucket, "cash", "현금/대기자금")
        merged_item = merged.get(key)
        if merged_item is None:
            merged_item = dict(item)
            if bucket == "cash":
                merged_item["display_name"] = "현금/대기자금"
                merged_item["security_code"] = None
                merged_item["role_summary"] = merged_item.get("role_summary") or "유동성 관리"
            merged_item["target_weight"] = weight
            merged[key] = merged_item
            continue
        merged_item["target_weight"] = float(merged_item.get("target_weight") or 0) + weight
        if not merged_item.get("role_summary") and item.get("role_summary"):
            merged_item["role_summary"] = item.get("role_summary")
    normalized = [
        item for item in merged.values() if abs(float(item.get("target_weight") or 0)) >= 1e-9
    ]
    return sorted(
        normalized,
        key=lambda item: float(item.get("target_weight") or 0),
        reverse=True,
    )


def _build_allocation_view(allocation_items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = _normalize_allocation_items(allocation_items)
    grouped = {"stock": [], "etf": [], "cash": []}
    sleeve_weights = {"stock": 0.0, "etf": 0.0, "cash": 0.0}
    for item in sorted_items:
        bucket = _allocation_bucket(item)
        grouped[bucket].append(item)
        sleeve_weights[bucket] += float(item.get("target_weight") or 0)
    sections = [
        {
            "bucket": "stock",
            "title": "주식 상위 종목",
            "items": grouped["stock"][:5],
            "all_items": grouped["stock"],
        },
        {
            "bucket": "etf",
            "title": "ETF 상위 종목",
            "items": grouped["etf"][:5],
            "all_items": grouped["etf"],
        },
        {
            "bucket": "cash",
            "title": "현금성 자산",
            "items": grouped["cash"],
            "all_items": grouped["cash"],
        },
    ]
    displayed_count = sum(len(section["items"]) for section in sections)
    return {
        "sleeves": [
            {"label": "주식 sleeve 비중", "bucket": "stock", "weight": sleeve_weights["stock"]},
            {"label": "ETF sleeve 비중", "bucket": "etf", "weight": sleeve_weights["etf"]},
            {"label": "현금성 비중", "bucket": "cash", "weight": sleeve_weights["cash"]},
        ],
        "sections": sections,
        "stock_items": grouped["stock"],
        "etf_items": grouped["etf"],
        "cash_items": grouped["cash"],
        "all_items": sorted_items,
        "extra_count": max(len(sorted_items) - displayed_count, 0),
    }


def _period_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    period = str(item.get("period") or "")
    return (PERIOD_DISPLAY_ORDER.get(period, 99), period)


def _build_period_metric_view(item: dict[str, Any]) -> dict[str, Any]:
    period = str(item.get("period") or "")
    use_total_return = period in RETURN_PERIODS
    headline_label = "Total Return" if use_total_return else "CAGR"
    headline_value = item.get("total_return") if use_total_return else item.get("cagr")
    if headline_value is None:
        headline_value = item.get("cagr")
    metric_view = dict(item)
    metric_view["headline_label"] = headline_label
    metric_view["headline_value"] = headline_value
    return metric_view


def _build_period_view(
    period_rows: list[dict[str, Any]],
    *,
    primary_period: str | None,
    reference_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordered_rows = sorted(period_rows, key=_period_sort_key)
    primary = next(
        (row for row in ordered_rows if row.get("period") == primary_period),
        None,
    )
    if primary is None and ordered_rows:
        primary = ordered_rows[0]
    if primary is not None:
        primary = _build_period_metric_view(primary)
    core_rows = [row for row in ordered_rows if row.get("period") not in REFERENCE_PERIODS]
    supporting_rows = [
        _build_period_metric_view(row)
        for row in core_rows
        if row.get("period") != (primary or {}).get("period")
    ]
    reference_rows: list[dict[str, Any]] = []
    return {
        "primary": primary,
        "supporting": supporting_rows,
        "reference": reference_rows,
        "ordered": [_build_period_metric_view(row) for row in ordered_rows],
    }


def _build_growth_note(service_profile: str, market_regime: str | None) -> str | None:
    if service_profile != "growth":
        return None
    if market_regime not in {"neutral", "risk_on", "bull"}:
        return None
    return (
        "중립 또는 위험선호 구간에서는 최근 1년 CAGR 우위가 있는 성장 주식 모델이 선택되며, "
        "현재 기준으로는 S3 성격의 성장 sleeve가 전면에 배치되는 것이 정상입니다."
    )


def _build_today_report_view(
    report: dict[str, Any],
    current_market_regime: str | None,
    model_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allocation_view = _build_allocation_view(report.get("allocation_items", []))
    performance_summary = report.get("performance_summary") or {}
    headline_metrics = performance_summary.get("headline_metrics") or {}
    period_rows = performance_summary.get("period_metrics") or []
    period_view = _build_period_view(
        period_rows,
        primary_period=headline_metrics.get("primary_period") or "1Y",
    )
    report_view = dict(report)
    report_view["allocation_view"] = allocation_view
    report_view["period_view"] = period_view
    report_view["quant_model_name"] = str(
        report.get("quant_model_name") or report.get("user_model_name") or "퀀트투자 모델"
    ).strip()
    report_view["model_definition_line"] = str(
        report.get("model_definition_line") or "공개 기준 기반 퀀트투자 모델"
    ).strip()
    report_view["model_definition_detail"] = str(
        report.get("model_definition_detail") or report.get("summary_text") or ""
    ).strip()
    report_view["growth_note"] = _build_growth_note(
        report.get("service_profile", ""),
        current_market_regime,
    )
    report_view["reference_usage_context"] = (model_info or {}).get("reference_usage_context") or (
        "공개 기준 기반 퀀트투자 모델 정보를 참고하려는 이용자"
    )
    report_view["compliance_metadata"] = (
        report.get("compliance_metadata") or (model_info or {}).get("compliance_metadata") or {}
    )
    return report_view


def _build_performance_row_view(row: dict[str, Any]) -> dict[str, Any]:
    cards = row.get("performance_cards") or {}
    period_view = _build_period_view(
        row.get("period_table") or [],
        primary_period=cards.get("primary_period") or "1Y",
        reference_metrics=row.get("reference_metrics") or {},
    )
    row_view = dict(row)
    row_view["period_view"] = period_view
    row_view["quant_model_name"] = str(
        row.get("quant_model_name") or row.get("user_model_name") or "퀀트투자 모델"
    ).strip()
    row_view["model_definition_line"] = str(
        row.get("model_definition_line") or "공개 기준 기반 퀀트투자 모델"
    ).strip()
    row_view["model_definition_detail"] = str(
        row.get("model_definition_detail") or row.get("note") or ""
    ).strip()
    return row_view


MARKET_CHANGE_DIRECTION_LABELS = {
    "up": "개선",
    "down": "약화",
    "unchanged": "변화 없음",
}

MARKET_METRIC_GROUPS = [
    (
        "지수/추세",
        [
            ("above_20dma_ratio", "20일선 위 종목 비율", "percent"),
            ("above_60dma_ratio", "60일선 위 종목 비율", "percent"),
        ],
    ),
    (
        "내부 breadth",
        [
            ("adv_dec_ratio", "상승/하락 비율", "ratio"),
            ("new_high_count", "신고가 종목 수", "count"),
            ("new_low_count", "신저가 종목 수", "count"),
        ],
    ),
    (
        "위험/변동성",
        [
            ("realized_vol_20d", "20일 실현 변동성", "percent"),
            ("drawdown_20d", "20일 최대 낙폭", "signed_percent"),
        ],
    ),
    (
        "환율/금리",
        [
            ("usdkrw_20d_ret", "원달러 20일 변화", "signed_percent"),
            ("rate_cd91_20d_chg", "CD 91일물 20일 변화", "signed_points"),
            ("rate_ktb3y_20d_chg", "국고채 3년 20일 변화", "signed_points"),
        ],
    ),
]


def _format_market_value(value: float | int | None, value_type: str) -> str:
    if value is None:
        return "-"
    if value_type == "percent":
        return f"{value * 100:.1f}%"
    if value_type == "signed_percent":
        return f"{value * 100:+.1f}%"
    if value_type == "signed_points":
        return f"{value:+.2f}%p"
    if value_type == "count":
        return f"{int(value):,}"
    return f"{value:.2f}"


def _build_market_metric_groups(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for title, items in MARKET_METRIC_GROUPS:
        rows = []
        for key, label, value_type in items:
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "value": metrics.get(key),
                    "display": _format_market_value(metrics.get(key), value_type),
                }
            )
        groups.append({"title": title, "items": rows})
    return groups


MARKET_STATE_TICK_LABELS = [
    "강하락",
    "하락",
    "약보합",
    "중립",
    "강보합",
    "상승",
    "강상승",
]


def _coerce_market_score(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_score_level(score: float | None) -> str:
    if score is None:
        return "중립"
    if score >= 2.0:
        return "강상승"
    if score >= 1.0:
        return "상승"
    if score >= 0.3:
        return "강보합"
    if score > -0.3:
        return "중립"
    if score > -1.0:
        return "약보합"
    if score > -2.0:
        return "하락"
    return "강하락"


def _market_score_percent(score: float | None) -> float:
    if score is None:
        return 50.0
    clamped = max(-3.0, min(3.0, score))
    return round(((clamped + 3.0) / 6.0) * 100.0, 2)


def _build_market_state_bar(
    *,
    label: str,
    score: Any,
    prev_label: str | None,
    change_direction: str | None,
    asof: str | None,
) -> dict[str, Any]:
    numeric_score = _coerce_market_score(score)
    return {
        "label": label or "데이터 준비 중",
        "score": numeric_score,
        "score_text": f"{numeric_score:.2f}" if numeric_score is not None else "-",
        "previous_label": prev_label or "-",
        "change_direction_label": MARKET_CHANGE_DIRECTION_LABELS.get(
            change_direction or "unchanged",
            "변화 없음",
        ),
        "level_label": _market_score_level(numeric_score),
        "position_percent": _market_score_percent(numeric_score),
        "asof": asof or "-",
        "asof_display": _format_kst_datetime(asof),
        "ticks": MARKET_STATE_TICK_LABELS,
    }


def _strip_reference_suffix(text: str, *, default: str) -> str:
    value = str(text or "").strip() or default
    if value.endswith(" 참고"):
        return value[:-3].strip()
    return value


def _build_market_state_bar_from_bundle(bundle: Any | None) -> dict[str, Any]:
    if bundle is None:
        return _build_market_state_bar(
            label="데이터 준비 중",
            score=None,
            prev_label="-",
            change_direction="unchanged",
            asof=None,
        )

    page = getattr(bundle, "page", {}) or {}
    home = getattr(bundle, "home", {}) or {}
    today = getattr(bundle, "today", {}) or {}
    header_state = page.get("header_state") or {}
    home_hero = home.get("hero") or {}
    today_bridge = today.get("market_bridge") or {}

    return _build_market_state_bar(
        label=(
            header_state.get("label")
            or home_hero.get("state_label")
            or today_bridge.get("state_label")
            or "데이터 준비 중"
        ),
        score=(
            header_state.get("score")
            if header_state.get("score") is not None
            else home_hero.get("state_score", today_bridge.get("state_score"))
        ),
        prev_label=header_state.get("prev_label") or home_hero.get("change_vs_prev") or "-",
        change_direction=header_state.get("change_direction") or "unchanged",
        asof=page.get("asof")
        or home.get("asof")
        or today.get("asof")
        or getattr(bundle, "asof", None),
    )


def _build_market_ai_briefs(ai_payload: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(ai_payload.get("enabled"))
    title = _strip_reference_suffix(
        str(ai_payload.get("title") or "퀀트투자 모델 브리핑 참고"),
        default="퀀트투자 모델 브리핑",
    )
    compliance_meta = ai_payload.get("compliance_meta") or {}
    providers = ai_payload.get("providers") or []
    cards: list[dict[str, Any]] = []
    for provider in providers:
        if not isinstance(provider, dict) or not provider.get("enabled"):
            continue
        summary_lines = [
            str(line).strip() for line in (provider.get("summary_lines") or []) if str(line).strip()
        ][:4]
        if not summary_lines:
            continue
        provider_name = provider.get("provider") or "unknown"
        provider_label = provider.get("label") or "AI 요약"
        theme_label = str(provider.get("theme_label") or "").strip()
        full_title = _strip_reference_suffix(
            theme_label or str(provider_label),
            default=str(provider_label),
        )
        sort_order = 90
        if provider_name == "gemini":
            provider_label = "Gemini"
            sort_order = 0
        elif provider_name == "chatgpt":
            provider_label = "ChatGPT"
            sort_order = 1
        cards.append(
            {
                "provider": provider_name,
                "label": provider_label,
                "full_title": full_title,
                "sort_order": sort_order,
                "source": provider.get("source") or "",
                "generated_at": provider.get("generated_at"),
                "summary_lines": summary_lines,
            }
        )
    cards.sort(key=lambda item: (item.get("sort_order", 99), item.get("label", "")))
    show_placeholder = enabled and not cards
    return {
        "enabled": enabled,
        "title": title,
        "cards": cards,
        "show_placeholder": show_placeholder,
        "placeholder": f"{title} 준비 중",
        "compliance_meta": compliance_meta,
    }


def _build_market_page_view(page_payload: dict[str, Any]) -> dict[str, Any]:
    page_meta = page_payload.get("page_meta") or {}
    header_state = page_payload.get("header_state") or {}
    signal_lists = page_payload.get("signal_lists") or {}
    notice_block = page_payload.get("notice_block") or {}
    usage_guide_card = page_payload.get("usage_guide_card") or {}
    compliance_meta = page_payload.get("compliance_meta") or {}
    component_cards = []
    for item in page_payload.get("component_cards") or []:
        status_badge = item.get("status_badge") or {}
        component_cards.append(
            {
                "key": item.get("key"),
                "label": item.get("label") or "-",
                "score": item.get("score"),
                "summary": item.get("summary") or "-",
                "description": str(item.get("description") or "").strip(),
                "status_badge": {
                    "label": str(status_badge.get("label") or "").strip(),
                    "tone": str(status_badge.get("tone") or "").strip() or "neutral",
                    "reason": str(status_badge.get("reason") or "").strip(),
                },
            }
        )
    return {
        "asof": page_payload.get("asof"),
        "page_title": str(page_meta.get("page_title") or "시장 브리핑").strip(),
        "page_subtitle": str(
            page_meta.get("page_subtitle")
            or page_payload.get("summary_line")
            or "시장 브리핑 데이터가 아직 준비되지 않았습니다."
        ).strip(),
        "service_definition": str(
            page_meta.get("service_definition")
            or page_payload.get("service_definition")
            or "다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보 서비스"
        ).strip(),
        "summary_line": page_payload.get("summary_line")
        or "시장 브리핑 데이터가 아직 준비되지 않았습니다.",
        "header_state": {
            "label": header_state.get("label") or "데이터 준비 중",
            "score": header_state.get("score"),
            "prev_label": header_state.get("prev_label") or "-",
            "change_direction": header_state.get("change_direction") or "unchanged",
            "description": str(header_state.get("description") or "").strip(),
            "tooltip": str(header_state.get("tooltip") or "").strip(),
            "change_direction_label": MARKET_CHANGE_DIRECTION_LABELS.get(
                header_state.get("change_direction") or "unchanged",
                "변화 없음",
            ),
        },
        "ai_briefs": _build_market_ai_briefs(page_payload.get("ai_briefs") or {}),
        "state_bar": _build_market_state_bar(
            label=header_state.get("label") or "데이터 준비 중",
            score=header_state.get("score"),
            prev_label=header_state.get("prev_label") or "-",
            change_direction=header_state.get("change_direction") or "unchanged",
            asof=page_payload.get("asof"),
        ),
        "component_cards": component_cards,
        "positive_points": signal_lists.get("positive_points") or [],
        "positive_label": str(signal_lists.get("positive_label") or "모델에 우호적인 신호").strip(),
        "warning_points": signal_lists.get("warning_points") or [],
        "warning_label": str(
            signal_lists.get("warning_label") or "모델 해석상 주의할 신호"
        ).strip(),
        "observation_title": str(
            signal_lists.get("observation_title") or "이번 주 모델 해석 포인트"
        ).strip(),
        "observation_description": str(
            signal_lists.get("observation_description")
            or "시장 브리핑을 모델 해석 참고용으로 읽는 핵심 포인트입니다."
        ).strip(),
        "observation_note": signal_lists.get("observation_note") or "-",
        "usage_guide_card": {
            "title": str(
                usage_guide_card.get("title") or "이 시장 브리핑은 어디에 쓰이나요?"
            ).strip(),
            "body": [
                str(line).strip()
                for line in (usage_guide_card.get("body") or [])
                if str(line).strip()
            ],
        },
        "metric_groups": _build_market_metric_groups(page_payload.get("metrics") or {}),
        "notice_block": {
            "title": notice_block.get("title") or "안내",
            "body": [
                str(line).strip() for line in (notice_block.get("body") or []) if str(line).strip()
            ],
            "performance_link_note": str(notice_block.get("performance_link_note") or "").strip(),
        },
        "compliance_meta": compliance_meta,
        "show_notice_block": bool(notice_block.get("body"))
        or bool(compliance_meta.get("disclaimer_required")),
        "source_rows": [
            {"label": "업데이트 주기", "value": "1시간"},
            {"label": "데이터 기준", "value": "국내 주요 시장 지표"},
            {"label": "안내", "value": "최신 공개 데이터 기준"},
        ],
    }


PREVIEW_CHANGE_TYPE_LABELS = {
    "new": "신규 편입",
    "exit": "제외",
    "increase": "비중 확대",
    "decrease": "비중 축소",
}

PREVIEW_CHANGE_TYPE_TONES = {
    "new": "accent",
    "increase": "accent",
    "exit": "neutral",
    "decrease": "neutral",
}

PREVIEW_MODEL_CODES_WITH_FALLBACK_ASSET_MIX = {"S3", "S3_CORE2"}


def _preview_model_title(model: dict[str, Any]) -> str:
    return str(model.get("display_name") or model.get("model_code") or "모델")


def _preview_asset_mix_rows(asset_mix: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "주식 비중", "value": asset_mix.get("stock_weight")},
        {"label": "ETF 비중", "value": asset_mix.get("etf_weight")},
        {"label": "현금성 비중", "value": asset_mix.get("cash_weight")},
    ]


def _build_preview_today_model_view(model: dict[str, Any]) -> dict[str, Any]:
    model_code = str(model.get("model_code") or "")
    metrics = dict(model.get("headline_metrics") or {})
    return {
        "model_code": model_code,
        "display_name": _preview_model_title(model),
        "risk_grade": model.get("risk_grade") or "-",
        "run_id": model.get("run_id") or "-",
        "backtest_period": model.get("backtest_period") or {},
        "headline_metrics": [
            {"label": "CAGR", "value": metrics.get("cagr"), "kind": "percent"},
            {"label": "MDD", "value": metrics.get("mdd"), "kind": "percent"},
            {"label": "Sharpe", "value": metrics.get("sharpe"), "kind": "number"},
            {
                "label": "현재 드로우다운",
                "value": metrics.get("current_drawdown"),
                "kind": "percent",
            },
            {"label": "최근 4주", "value": metrics.get("return_4w"), "kind": "percent"},
            {"label": "최근 12주", "value": metrics.get("return_12w"), "kind": "percent"},
        ],
        "asset_mix_rows": _preview_asset_mix_rows(model.get("asset_mix") or {}),
        "asset_mix_reference_only": model_code in PREVIEW_MODEL_CODES_WITH_FALLBACK_ASSET_MIX,
        "recent_change_cards": [
            {
                "label": "신규 8주",
                "value": (model.get("recent_change_summary") or {}).get("new_8w", 0),
            },
            {
                "label": "제외 8주",
                "value": (model.get("recent_change_summary") or {}).get("exit_8w", 0),
            },
            {
                "label": "비중 확대",
                "value": (model.get("recent_change_summary") or {}).get("increase_8w", 0),
            },
            {
                "label": "비중 축소",
                "value": (model.get("recent_change_summary") or {}).get("decrease_8w", 0),
            },
        ],
        "top_holdings": list(model.get("top_holdings") or [])[:8],
        "holding_highlights": list(model.get("holding_highlights") or [])[:5],
    }


def _build_preview_change_model_view(model: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in model.get("items") or []:
        change_type = str(item.get("change_type") or "").lower()
        items.append(
            {
                "week_end": item.get("week_end") or "-",
                "ticker": item.get("ticker") or "-",
                "name": item.get("name") or "종목명 미표시",
                "asset_type": item.get("asset_type") or "-",
                "change_type": change_type,
                "change_label": PREVIEW_CHANGE_TYPE_LABELS.get(change_type, change_type or "변화"),
                "change_tone": PREVIEW_CHANGE_TYPE_TONES.get(change_type, "neutral"),
                "weight_prev": item.get("weight_prev"),
                "weight_curr": item.get("weight_curr"),
                "delta_weight": item.get("delta_weight"),
            }
        )
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "summary_cards": [
            {"label": "신규 8주", "value": (model.get("summary") or {}).get("new_8w", 0)},
            {"label": "제외 8주", "value": (model.get("summary") or {}).get("exit_8w", 0)},
            {"label": "비중 확대", "value": (model.get("summary") or {}).get("increase_8w", 0)},
            {"label": "비중 축소", "value": (model.get("summary") or {}).get("decrease_8w", 0)},
        ],
        "items": items,
    }


def _build_preview_compare_row(row: dict[str, Any]) -> dict[str, Any]:
    model_code = str(row.get("model_code") or "")
    return {
        "model_code": model_code,
        "display_name": _preview_model_title(row),
        "risk_grade": row.get("risk_grade") or "-",
        "cagr": row.get("cagr"),
        "mdd": row.get("mdd"),
        "sharpe": row.get("sharpe"),
        "return_4w": row.get("return_4w"),
        "return_12w": row.get("return_12w"),
        "current_drawdown": row.get("current_drawdown"),
        "relative_strength_vs_benchmark_4w": row.get("relative_strength_vs_benchmark_4w"),
        "asset_mix_rows": _preview_asset_mix_rows(
            {
                "stock_weight": row.get("stock_weight"),
                "etf_weight": row.get("etf_weight"),
                "cash_weight": row.get("cash_weight"),
            }
        ),
        "change_cards": [
            {"label": "신규 8주", "value": row.get("new_8w", 0)},
            {"label": "제외 8주", "value": row.get("exit_8w", 0)},
            {"label": "비중 확대", "value": row.get("increase_8w", 0)},
            {"label": "비중 축소", "value": row.get("decrease_8w", 0)},
        ],
        "asset_mix_reference_only": model_code in PREVIEW_MODEL_CODES_WITH_FALLBACK_ASSET_MIX,
    }


def _preview_breakdown_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(rows or [], start=1):
        normalized.append(
            {
                "rank_no": row.get("rank_no") or index,
                "ticker": row.get("ticker") or "-",
                "name": row.get("name") or "종목명 미표시",
                "asset_type": row.get("asset_type") or "-",
                "weight": row.get("weight"),
            }
        )
    return normalized


def _preview_mix_segments(asset_mix: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": "주식", "value": asset_mix.get("stock_weight"), "tone": "stock"},
        {"label": "ETF", "value": asset_mix.get("etf_weight"), "tone": "etf"},
        {"label": "현금성", "value": asset_mix.get("cash_weight"), "tone": "cash"},
        {"label": "기타", "value": asset_mix.get("other_weight"), "tone": "other"},
    ]


def _build_preview_portfolio_structure_view(model: dict[str, Any]) -> dict[str, Any]:
    latest_asset_mix = model.get("latest_asset_mix") or {}
    concentration = model.get("concentration") or {}
    quality_context = model.get("quality_context") or {}
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "risk_grade": model.get("risk_grade") or "-",
        "mix_segments": _preview_mix_segments(latest_asset_mix),
        "trend_rows": [
            {
                "week_end": row.get("week_end") or "-",
                "segments": _preview_mix_segments(row),
            }
            for row in (model.get("asset_mix_trend_26w") or [])[-26:]
        ],
        "breakdown_rows": _preview_breakdown_rows(model.get("current_allocation_breakdown") or []),
        "concentration_cards": [
            {"label": "Top 1 비중", "value": concentration.get("top1_weight"), "kind": "percent"},
            {"label": "Top 3 비중", "value": concentration.get("top3_weight"), "kind": "percent"},
            {"label": "Top 5 비중", "value": concentration.get("top5_weight"), "kind": "percent"},
            {
                "label": "현재 보유 수",
                "value": concentration.get("current_holdings_count", 0),
                "kind": "count",
            },
        ],
        "quality_cards": [
            {"label": "최근 4주", "value": quality_context.get("return_4w"), "kind": "percent"},
            {"label": "최근 12주", "value": quality_context.get("return_12w"), "kind": "percent"},
            {
                "label": "평균 현금성(4주)",
                "value": quality_context.get("cash_weight_avg_4w"),
                "kind": "percent",
            },
            {
                "label": "평균 보유 수(4주)",
                "value": quality_context.get("holdings_count_avg_4w", 0),
                "kind": "count",
            },
        ],
        "asset_mix_reference_only": str(model.get("model_code") or "")
        in PREVIEW_MODEL_CODES_WITH_FALLBACK_ASSET_MIX,
    }


def _preview_lifecycle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows or []:
        normalized.append(
            {
                "ticker": row.get("ticker") or "-",
                "name": row.get("name") or "종목명 미표시",
                "asset_type": row.get("asset_type") or "-",
                "first_seen_date": row.get("first_seen_date") or "-",
                "last_seen_date": row.get("last_seen_date") or "-",
                "holding_days_observed": row.get("holding_days_observed", 0),
                "latest_weight": row.get("latest_weight"),
                "latest_return_since_entry": row.get("latest_return_since_entry"),
                "week_end": row.get("week_end") or "-",
                "delta_weight": row.get("delta_weight"),
            }
        )
    return normalized


def _build_preview_holding_lifecycle_view(model: dict[str, Any]) -> dict[str, Any]:
    current_holdings = _preview_lifecycle_rows(model.get("current_holdings_lifecycle") or [])
    longest_holdings = _preview_lifecycle_rows(model.get("longest_historical_holdings") or [])
    recent_entries = _preview_lifecycle_rows(model.get("recent_new_entries_8w") or [])
    recent_exits = _preview_lifecycle_rows(model.get("recent_exits_8w") or [])
    highlights = _preview_lifecycle_rows(model.get("current_holding_highlights") or [])
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "summary_cards": [
            {"label": "현재 보유", "value": len(current_holdings)},
            {"label": "장기 이력", "value": len(longest_holdings)},
            {"label": "신규 8주", "value": len(recent_entries)},
            {"label": "제외 8주", "value": len(recent_exits)},
        ],
        "current_holdings": current_holdings,
        "longest_holdings": longest_holdings[:12],
        "recent_entries": recent_entries[:12],
        "recent_exits": recent_exits[:12],
        "highlights": highlights,
    }


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    logger = configure_logging(settings.log_level)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = settings.session_secret_key
    provider = SnapshotDataProvider(settings)
    user_snapshot_api = UserSnapshotMockApi(settings)
    market_analysis_api = MarketAnalysisMockApi(settings)
    analytics_preview_api = AnalyticsPreviewApi(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    analytics_preview_p2_api = AnalyticsPreviewP2Api(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    feedback_store = FeedbackStore(settings)
    access_store = AccessStore(settings)
    billing_service = BillingService(settings, access_store)

    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        access_store.ensure_bootstrap_admin(
            email=settings.bootstrap_admin_email,
            password=settings.bootstrap_admin_password,
        )

    app.config["SETTINGS"] = settings
    app.config["SNAPSHOT_PROVIDER"] = provider
    app.config["USER_SNAPSHOT_API"] = user_snapshot_api
    app.config["MARKET_ANALYSIS_API"] = market_analysis_api
    app.config["ANALYTICS_PREVIEW_API"] = analytics_preview_api
    app.config["ANALYTICS_PREVIEW_P2_API"] = analytics_preview_p2_api
    app.config["FEEDBACK_STORE"] = feedback_store
    app.config["ACCESS_STORE"] = access_store
    app.config["BILLING_SERVICE"] = billing_service

    def current_access_context() -> AccessContext:
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            return access_store.get_effective_access(None)
        return access_store.get_effective_access(user_id)

    def current_user_orders() -> list[dict]:
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            return []
        return access_store.list_orders_for_user(user_id)

    def get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not isinstance(token, str) or not token:
            token = secrets.token_urlsafe(24)
            session["csrf_token"] = token
        return token

    def require_csrf() -> None:
        expected = session.get("csrf_token")
        provided = request.form.get("csrf_token", "")
        if not expected or not provided or provided != expected:
            abort(400)

    def _normalize_phone_number(phone_number: str) -> str:
        return "".join(ch for ch in phone_number if ch.isdigit())

    def issue_phone_verification(phone_number: str) -> str:
        normalized_phone = _normalize_phone_number(phone_number)
        if len(normalized_phone) < 10 or len(normalized_phone) > 11:
            raise RegistrationValidationError("휴대폰 번호는 숫자 10~11자리로 입력해 주세요.")
        verification_code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = (
            datetime.utcnow() + timedelta(seconds=settings.phone_verification_code_ttl_seconds)
        ).isoformat()
        session["phone_verification"] = {
            "phone_number": normalized_phone,
            "code": verification_code,
            "expires_at": expires_at,
        }
        return verification_code

    def is_phone_verification_valid(phone_number: str, verification_code: str) -> bool:
        payload = session.get("phone_verification") or {}
        if payload.get("phone_number") != _normalize_phone_number(phone_number):
            return False
        if payload.get("code") != verification_code.strip():
            return False
        expires_at = payload.get("expires_at")
        if not expires_at:
            return False
        try:
            expires = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
        if datetime.utcnow() > expires:
            return False
        return True

    def clear_phone_verification() -> None:
        session.pop("phone_verification", None)

    def admin_url(endpoint: str) -> str:
        return url_for(endpoint)

    def build_admin_links() -> dict[str, str]:
        links = {
            "dashboard": admin_url("admin_dashboard"),
            "users": admin_url("admin_users"),
            "grant": admin_url("admin_grant"),
            "plans": admin_url("admin_plans_entitlements"),
            "publish": admin_url("admin_publish_snapshots"),
            "feedback": admin_url("admin_feedback"),
            "metrics": admin_url("admin_metrics"),
            "audit": admin_url("admin_audit"),
        }
        if settings.billing_enabled:
            links["billing"] = admin_url("admin_billing")
        return links

    def require_admin_access() -> AccessContext:
        access_context = current_access_context()
        if not require_admin(request, settings, access_context):
            abort(404)
        return access_context

    def require_internal_preview_access() -> AccessContext:
        access_context = require_admin_access()
        if settings.app_env != "production":
            return access_context
        allowed_emails = {email.lower() for email in settings.analytics_preview_allowed_emails}
        current_email = str((access_context.user.email if access_context.user else "")).lower()
        if current_email not in allowed_emails:
            abort(404)
        return access_context

    def build_analytics_preview_links() -> dict[str, str]:
        return {
            "today": url_for("admin_preview_today_model_info"),
            "changes": url_for("admin_preview_model_changes"),
            "compare": url_for("admin_preview_model_compare"),
        }

    def load_analytics_preview_bundle(force_refresh: bool = False):
        return analytics_preview_api.load_bundle(force_refresh=force_refresh)

    def build_analytics_preview_p2_links() -> dict[str, str]:
        return {
            "portfolio": url_for("admin_preview_portfolio_structure"),
            "lifecycle": url_for("admin_preview_holding_lifecycle"),
        }

    def load_analytics_preview_p2_bundle(force_refresh: bool = False):
        return analytics_preview_p2_api.load_bundle(force_refresh=force_refresh)

    def audit_admin(
        *,
        access_context: AccessContext,
        action_type: str,
        target_type: str,
        target_id: str | None,
        payload_summary: dict | str,
        result: str,
    ) -> None:
        summary_text = (
            payload_summary
            if isinstance(payload_summary, str)
            else json.dumps(payload_summary, ensure_ascii=False, sort_keys=True)
        )
        access_store.record_audit_log(
            admin_user_id=access_context.user.id if access_context.user else None,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            payload_summary=summary_text,
            result=result,
            ip_address=_request_ip_address(),
        )

    def safe_metrics_summary() -> dict:
        try:
            return feedback_store.get_metrics_summary()
        except Exception as exc:  # pragma: no cover
            logger.warning("metrics_summary_failed error=%s", exc)
            return {
                "window_hours": settings.analytics_window_hours,
                "page_views": 0,
                "today_page_views": 0,
                "feedback_submissions": 0,
                "ticker_clicks": [],
                "model_interest": [],
            }

    def safe_record_event(**kwargs) -> None:
        try:
            feedback_store.record_event(**kwargs)
        except Exception as exc:  # pragma: no cover
            logger.warning("event_record_failed error=%s", exc)

    def safe_list_recent_feedback(limit: int = 100) -> list[dict]:
        try:
            return feedback_store.list_recent_feedback(limit=limit)
        except Exception as exc:  # pragma: no cover
            logger.warning("feedback_list_failed error=%s", exc)
            return []

    def maybe_alert_status(status_snapshot) -> None:
        if status_snapshot.state == "healthy":
            return
        run_id = getattr(status_snapshot, "last_run_id", None)
        errors = getattr(status_snapshot, "errors", [])
        send_alert(
            settings,
            title="Snapshot Status Warning",
            message=(
                f"state={status_snapshot.state} as_of={status_snapshot.as_of_date} "
                f"run_id={run_id} errors={' | '.join(errors)}"
            ),
            alert_key=f"snapshot_status_{status_snapshot.state}",
        )

    def render_snapshot_error(status_code: int = 503) -> tuple[str, int]:
        status_snapshot = provider.get_status(force_refresh=False)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        return (
            render_template(
                "error.html",
                page_title="Snapshot Unavailable",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                message="현재 데이터 업데이트 중입니다. 잠시 후 다시 시도해 주세요.",
            ),
            status_code,
        )

    def load_or_error():
        try:
            return provider.load_bundle(force_refresh=False)
        except SnapshotLoadError:
            return None

    def load_user_bundle_or_error():
        try:
            return user_snapshot_api.load_bundle(force_refresh=False)
        except UserSnapshotLoadError:
            return None

    def load_market_bundle_or_error():
        try:
            return market_analysis_api.load_bundle(force_refresh=False)
        except MarketAnalysisLoadError:
            return None

    def render_user_snapshot_error(status_code: int = 503) -> tuple[str, int]:
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        return (
            render_template(
                "error.html",
                page_title="Snapshot Unavailable",
                status_snapshot=status_snapshot,
                metrics_summary=safe_metrics_summary(),
                message="현재 사용자용 스냅샷을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            ),
            status_code,
        )

    def record_page_view(page: str, bundle=None) -> None:
        meta = {}
        access_context = current_access_context()
        meta["effective_plan_id"] = access_context.effective_plan_id
        if bundle and bundle.generated_at:
            meta["publish_generated_at"] = bundle.generated_at
        safe_record_event(event_name="page_view", page=page, meta=meta)

    def ensure_billing_enabled() -> None:
        if not settings.billing_enabled:
            abort(404)

    def build_published_snapshot_rows() -> list[dict[str, str | None]]:
        published_root = settings.public_data_dir / PUBLISHED_DIRNAME
        if not published_root.exists():
            return []
        rows: list[dict[str, str | None]] = []
        for day_dir in sorted(
            [path for path in published_root.iterdir() if path.is_dir()], reverse=True
        ):
            for run_dir in sorted(
                [path for path in day_dir.iterdir() if path.is_dir()], reverse=True
            ):
                manifest_path = run_dir / MANIFEST_FILENAME
                manifest = {}
                if manifest_path.exists():
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                    except json.JSONDecodeError:
                        manifest = {}
                rows.append(
                    {
                        "label": run_dir.relative_to(published_root).as_posix(),
                        "as_of_date": manifest.get("as_of_date"),
                        "generated_at": manifest.get("generated_at"),
                        "run_id": manifest.get("run_id"),
                    }
                )
        return rows

    def activate_snapshot_label(snapshot_label: str) -> None:
        published_root = settings.public_data_dir / PUBLISHED_DIRNAME
        source_dir = (published_root / snapshot_label).resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise AdminValidationError("선택한 published 스냅샷을 찾지 못했습니다.")
        if published_root.resolve() not in source_dir.parents:
            raise AdminValidationError("허용되지 않은 스냅샷 경로입니다.")
        current_dir = settings.public_data_dir / CURRENT_DIRNAME
        tmp_root = settings.public_data_dir / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        staged_dir = tmp_root / f"admin-stage-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        previous_dir = tmp_root / f"admin-prev-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        shutil.copytree(source_dir, staged_dir)
        try:
            if current_dir.exists():
                current_dir.replace(previous_dir)
            staged_dir.replace(current_dir)
        finally:
            if staged_dir.exists():
                shutil.rmtree(staged_dir, ignore_errors=True)
            if previous_dir.exists():
                shutil.rmtree(previous_dir, ignore_errors=True)
        provider.load_bundle(force_refresh=True)

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        access_context = current_access_context()
        return {
            "service_name": "redbot",
            "current_user": access_context.user,
            "access_context": access_context,
            "status_messages": STATUS_MESSAGES,
            "billing_enabled": settings.billing_enabled,
            "billing_messages": BILLING_MESSAGES,
            "csrf_token": get_csrf_token(),
            "policy_state": get_policy_state(settings),
            "profile_labels": {
                "stable": "안정형",
                "balanced": "균형형",
                "growth": "성장형",
                "auto": "자동전환형",
            },
            "risk_labels": {
                "low": "낮음",
                "medium": "중간",
                "high": "높음",
                "adaptive": "적응형",
            },
            "regime_labels": {
                "bull": "상승",
                "bear": "하락",
                "neutral": "중립",
                "mixed": "혼합",
            },
            "change_type_labels": {
                "rebalanced": "리밸런싱",
                "increase": "비중 확대",
                "decrease": "비중 축소",
                "hold": "유지",
            },
            "status_labels": {
                "healthy": "정상",
                "warning": "주의",
                "stale": "업데이트 지연",
                "empty": "데이터 준비 중",
                "error": "일시 오류",
            },
            "market_status_labels": {
                "healthy": "정상",
                "warning": "주의",
                "stale": "업데이트 지연",
                "empty": "데이터 준비 중",
                "error": "일시 오류",
            },
        }

    @app.after_request
    def apply_admin_headers(response: Response) -> Response:
        if request.path.startswith("/admin"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.template_filter("fmt_datetime")
    def fmt_datetime(value: str | None) -> str:
        return _format_datetime(value)

    @app.template_filter("fmt_percent")
    def fmt_percent(value: float | int | None) -> str:
        return _format_percent(value)

    @app.template_filter("fmt_signed_percent")
    def fmt_signed_percent(value: float | int | None) -> str:
        if value is None:
            return "-"
        return f"{value * 100:+.2f}%"

    @app.template_filter("fmt_sharpe")
    def fmt_sharpe(value: float | int | None) -> str:
        if value is None:
            return "-"
        return f"{float(value):.2f}"

    @app.get("/api/v1/model-catalog")
    def api_user_models() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.user_models), 200)

    @app.get("/api/v1/model-weekly/today")
    @app.get("/api/v1/model-snapshots/today")
    def api_model_snapshots_today() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(user_snapshot_api.get_model_snapshots_today(force_refresh=False)), 200)

    @app.get("/api/v1/model-weekly/<service_profile>")
    @app.get("/api/v1/model-snapshots/<service_profile>")
    def api_model_snapshot_by_profile(service_profile: str) -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        report_payload = user_snapshot_api.get_model_snapshot_by_profile(service_profile)
        if report_payload is None:
            return ({"status": "not_found", "message": "service profile not found"}, 404)
        return (jsonify(report_payload), 200)

    @app.get("/api/v1/model-performance/summary")
    @app.get("/api/v1/performance/summary")
    def api_performance_summary() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.performance_summary), 200)

    @app.get("/api/v1/changes/recent")
    def api_changes_recent() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.recent_changes), 200)

    @app.get("/api/v1/publish-status")
    @app.get("/api/v1/manifest")
    def api_publish_status() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.publish_status), 200)

    @app.get("/api/v1/market-brief/home")
    @app.get("/api/v1/market-analysis/home")
    def api_market_analysis_home() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_home")), 200)

    @app.get("/api/v1/market-brief/page")
    @app.get("/api/v1/market-analysis/page")
    def api_market_analysis_page() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_page")), 200)

    @app.get("/api/v1/market-brief/summary")
    @app.get("/api/v1/market-analysis/summary")
    def api_market_analysis_summary() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_summary")), 200)

    @app.get("/api/v1/market-brief/detail")
    @app.get("/api/v1/market-analysis/detail")
    def api_market_analysis_detail() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_detail")), 200)

    @app.get("/api/v1/market-analysis/today-bridge")
    def api_market_analysis_today_bridge() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_today_bridge")), 200)

    @app.get("/api/v1/market-analysis/manifest")
    def api_market_analysis_manifest() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("manifest")), 200)

    @app.get("/")
    def home() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        market_bundle = load_market_bundle_or_error()
        record_page_view("/", bundle)
        performance_by_profile = {
            row.get("service_profile"): row for row in bundle.performance_summary.get("models", [])
        }
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        market_status_snapshot = market_analysis_api.get_status(force_refresh=False)
        return Response(
            render_template(
                "home.html",
                page_title="홈",
                bundle=bundle,
                performance_by_profile=performance_by_profile,
                status_snapshot=status_snapshot,
                market_home_payload=(market_bundle.home if market_bundle else {}),
                market_state_bar=_build_market_state_bar_from_bundle(market_bundle),
                market_status_snapshot=market_status_snapshot,
                compliance_note=_build_public_model_compliance_note(bundle),
                notice_blocks=_build_notice_blocks("service_nature", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/theme-preview")
    def theme_preview() -> Response:
        record_page_view("/theme-preview")
        return Response(
            render_template("theme_preview.html", page_title="Theme Preview"), mimetype="text/html"
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Response:
        next_url = _safe_next_url(request.values.get("next"))
        if request.method == "GET":
            record_page_view("/login")
            return Response(
                render_template(
                    "login.html",
                    page_title="로그인",
                    status=request.args.get("status", ""),
                    next_url=next_url,
                ),
                mimetype="text/html",
            )

        require_csrf()
        try:
            user = access_store.authenticate_local(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
            )
        except LoginValidationError:
            return redirect(url_for("login", status="invalid", next=next_url))

        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(24)
        return redirect(next_url)

    @app.route("/signup", methods=["GET", "POST"])
    def signup() -> Response:
        next_url = _safe_next_url(request.values.get("next") or url_for("today"))
        if request.method == "GET":
            record_page_view("/signup")
            verification_payload = session.get("phone_verification") or {}
            preview_code = ""
            if settings.phone_verification_preview_enabled:
                preview_code = session.get("phone_verification_preview", "")
            return Response(
                render_template(
                    "signup.html",
                    page_title="회원가입",
                    status=request.args.get("status", ""),
                    next_url=next_url,
                    phone_number=request.args.get(
                        "phone",
                        verification_payload.get("phone_number", ""),
                    ),
                    preview_code=preview_code,
                ),
                mimetype="text/html",
            )

        require_csrf()
        action = request.form.get("action", "register")
        next_url = _safe_next_url(request.form.get("next"))
        if action == "request_code":
            phone_number = request.form.get("phone_number", "")
            try:
                verification_code = issue_phone_verification(phone_number)
                session["phone_verification_preview"] = verification_code
                status = "code_sent"
            except RegistrationValidationError:
                status = "error"
            return redirect(url_for("signup", status=status, next=next_url, phone=phone_number))

        phone_number = request.form.get("phone_number", "")
        verification_code = request.form.get("verification_code", "")
        if not is_phone_verification_valid(phone_number, verification_code):
            return redirect(
                url_for("signup", status="code_invalid", next=next_url, phone=phone_number)
            )
        if request.form.get("password", "") != request.form.get("password_confirm", ""):
            return redirect(url_for("signup", status="error", next=next_url, phone=phone_number))

        try:
            access_store.register_local_user(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
                phone_number=phone_number,
            )
        except RegistrationValidationError as exc:
            status = "email_exists" if "이미 가입된 이메일" in str(exc) else "error"
            return redirect(url_for("signup", status=status, next=next_url, phone=phone_number))

        clear_phone_verification()
        session.pop("phone_verification_preview", None)
        return redirect(url_for("login", status="signup_success", next=next_url))

    @app.route("/logout", methods=["GET", "POST"])
    def logout() -> Response:
        session.clear()
        return redirect(url_for("login", status="logged_out"))

    @app.get("/me")
    def me() -> tuple[dict[str, object], int]:
        access_context = current_access_context()
        user = access_context.user
        profile = access_store.get_user_profile(user.id) if user else {}
        return (
            jsonify(
                {
                    "authenticated": access_context.authenticated,
                    "email": user.email if user else None,
                    "roles": list(access_context.roles),
                    "base_plan_id": access_context.base_plan_id,
                    "effective_plan_id": access_context.effective_plan_id,
                    "trial_active": access_context.trial_active,
                    "trial_end_date": access_context.trial_end_date,
                    "entitlements": access_context.entitlements,
                    "is_admin": access_context.is_admin,
                    "auth_provider": profile.get("auth_provider"),
                    "phone_number": profile.get("phone_number"),
                    "phone_verification_status": profile.get("phone_verification_status"),
                    "recent_orders": current_user_orders(),
                }
            ),
            200,
        )

    @app.get("/pricing")
    def pricing() -> Response:
        access_context = current_access_context()
        record_page_view("/pricing")
        return Response(
            render_template(
                "pricing.html",
                page_title="서비스 이용권 안내",
                plan_rows=billing_service.list_paid_plans(),
                billing_enabled=settings.billing_enabled,
                selected_method=request.args.get("pay_method", "CARD"),
                status=request.args.get("status", ""),
                current_orders=current_user_orders(),
                access_context=access_context,
                notice_blocks=_build_notice_blocks("service_nature", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.post("/billing/checkout")
    def billing_checkout() -> Response:
        ensure_billing_enabled()
        require_csrf()
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("pricing"), status="invalid"))
        try:
            form, ord_no = billing_service.create_checkout(
                user_id=access_context.user.id,
                user_email=access_context.user.email,
                plan_id=request.form.get("plan_id", ""),
                pay_method=request.form.get("pay_method", ""),
            )
        except (BillingDisabledError, LightPayValidationError):
            return redirect(url_for("pricing", status="invalid"))
        return Response(
            render_template(
                "billing_checkout.html",
                page_title="결제 진행",
                checkout_form=form,
                ord_no=ord_no,
            ),
            mimetype="text/html",
        )

    @app.route("/billing/return", methods=["GET", "POST"])
    def billing_return() -> Response:
        ensure_billing_enabled()
        payload = {key: value for key, value in request.values.items()}
        try:
            result = billing_service.handle_return(payload)
        except BillingDisabledError:
            abort(404)
        return Response(
            render_template(
                "billing_result.html",
                page_title="결제 결과",
                billing_result=result,
                source="return",
            ),
            mimetype="text/html",
        )

    @app.post("/billing/notify")
    def billing_notify() -> tuple[dict[str, object], int]:
        ensure_billing_enabled()
        if not _is_notify_ip_allowed(settings):
            logger.warning("billing_notify_ip_blocked ip=%s", _request_ip_address())
            return (jsonify({"status": "forbidden", "message": "notify sender blocked"}), 403)
        payload = {key: value for key, value in request.form.items()}
        try:
            result = billing_service.handle_notify(payload)
        except BillingDisabledError:
            abort(404)
        status_code = 200 if result.status in {"approved", "duplicate", "ignored"} else 400
        return (
            jsonify(
                {
                    "status": result.status,
                    "message": result.message,
                    "ord_no": result.ord_no,
                    "plan_id": result.plan_id,
                    "duplicate": result.duplicate,
                }
            ),
            status_code,
        )

    @app.get("/today")
    def today() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        market_bundle = load_market_bundle_or_error()
        record_page_view("/today", bundle)
        current_market_regime = bundle.recommendation_today.get("current_market_regime")
        model_lookup = {
            model.get("service_profile"): model for model in bundle.user_models.get("models", [])
        }
        report_views = [
            _build_today_report_view(
                report, current_market_regime, model_lookup.get(report.get("service_profile"))
            )
            for report in bundle.recommendation_today.get("reports", [])
        ]
        for report in report_views:
            safe_record_event(
                event_name="model_section_view",
                page="/today",
                model_id=report.get("service_profile"),
            )
        return Response(
            render_template(
                "today.html",
                page_title="이번 주 모델 기준안",
                bundle=bundle,
                status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                report_views=report_views,
                market_today_payload=(market_bundle.today if market_bundle else {}),
                market_state_bar=_build_market_state_bar_from_bundle(market_bundle),
                market_status_snapshot=market_analysis_api.get_status(force_refresh=False),
                compliance_note=_build_public_model_compliance_note(bundle),
                notice_blocks=_build_notice_blocks("service_nature", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/changes")
    def changes() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/changes", bundle)
        user_status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        maybe_alert_status(user_status_snapshot)
        publish_status_payload = None
        if user_status_snapshot.snapshot_accessible:
            publish_status_payload = user_snapshot_api.get_publish_status(force_refresh=False)
        return Response(
            render_template(
                "changes.html",
                page_title="변경내역",
                bundle=bundle,
                status_snapshot=user_status_snapshot,
                publish_status_payload=publish_status_payload,
                change_rows=bundle.recent_changes.get("changes", []),
            ),
            mimetype="text/html",
        )

    @app.get("/performance")
    def performance() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/performance", bundle)
        performance_rows = [
            _build_performance_row_view(row) for row in bundle.performance_summary.get("models", [])
        ]
        performance_by_profile = {
            row.get("service_profile"): row
            for row in performance_rows
            if row.get("service_profile")
        }
        balanced_cards = (performance_by_profile.get("balanced") or {}).get(
            "performance_cards"
        ) or {}
        auto_cards = (performance_by_profile.get("auto") or {}).get("performance_cards") or {}
        auto_balanced_same = (
            bool(balanced_cards) and bool(auto_cards) and balanced_cards == auto_cards
        )
        return Response(
            render_template(
                "performance.html",
                page_title="성과 설명",
                bundle=bundle,
                status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                performance_rows=performance_rows,
                auto_balanced_same=auto_balanced_same,
                notice_blocks=_build_notice_blocks("backtest", "risk", "non_advice"),
            ),
            mimetype="text/html",
        )

    @app.get("/market-analysis")
    def market_analysis() -> Response:
        market_bundle = load_market_bundle_or_error()
        market_status_snapshot = market_analysis_api.get_status(force_refresh=False)
        page_view = _build_market_page_view((market_bundle.page if market_bundle else {}))
        record_page_view("/market-analysis")
        return Response(
            render_template(
                "market_analysis.html",
                page_title=page_view.get("page_title", "시장 브리핑"),
                market_page_view=page_view,
                market_state_bar=page_view.get("state_bar"),
                market_status_snapshot=market_status_snapshot,
                notice_blocks=_build_notice_blocks("market_brief", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/feedback")
    def feedback() -> Response:
        record_page_view("/feedback")
        return Response(
            render_template(
                "feedback.html", page_title="의견 보내기", status=request.args.get("status", "")
            ),
            mimetype="text/html",
        )

    @app.post("/feedback")
    def submit_feedback() -> Response:
        require_csrf()
        submission = build_feedback_submission(request)
        try:
            feedback_store.submit_feedback(submission)
            return redirect(build_feedback_redirect(url_for("feedback"), status="success"))
        except FeedbackValidationError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="invalid"))
        except FeedbackRateLimitError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="rate_limited"))
        except FeedbackDuplicateError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="duplicate"))
        except Exception as exc:  # pragma: no cover
            logger.warning("feedback_submit_failed error=%s", exc)
            send_alert(
                settings,
                title="Feedback Submit Failed",
                message=f"Feedback submit failed on page={submission.page}: {exc}",
                alert_key="feedback_submit_failed",
            )
            return redirect(build_feedback_redirect(url_for("feedback"), status="error"))

    @app.get("/privacy")
    def privacy() -> Response:
        record_page_view("/privacy")
        return Response(
            render_template("privacy.html", page_title="개인정보 안내"), mimetype="text/html"
        )

    @app.get("/e/click")
    def track_click() -> Response:
        ticker = request.args.get("ticker", "")
        model_id = request.args.get("model_id", "")
        if not ticker:
            abort(400)
        target = _ticker_target_url(ticker)
        safe_record_event(
            event_name="ticker_click",
            page=request.args.get("page", "/today"),
            model_id=model_id or None,
            ticker=ticker,
            meta={"target": target},
        )
        return redirect(target)

    @app.get("/admin")
    def admin_dashboard() -> Response:
        access_context = require_admin_access()
        status_snapshot = provider.get_status(force_refresh=False)
        metrics_summary = safe_metrics_summary()
        dashboard_summary = access_store.get_dashboard_summary()
        return Response(
            render_template(
                "admin/dashboard.html",
                page_title="Admin Dashboard",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                dashboard_summary=dashboard_summary,
                audit_rows=access_store.list_recent_audit_logs(limit=10),
                published_rows=build_published_snapshot_rows()[:10],
                policy_state=get_policy_state(settings),
                access_context=access_context,
            ),
            mimetype="text/html",
        )

    @app.route("/admin/users", methods=["GET", "POST"])
    def admin_users() -> Response:
        access_context = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "")
            email = request.form.get("email", "")
            try:
                if action == "lock":
                    access_store.set_user_active(email=email, is_active=False)
                    status = "locked"
                elif action == "unlock":
                    access_store.set_user_active(email=email, is_active=True)
                    status = "unlocked"
                else:
                    raise AdminValidationError("지원하지 않는 action 입니다.")
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.users.{action}",
                    target_type="user",
                    target_id=email,
                    payload_summary={"email": email},
                    result="success",
                )
            except AdminValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.users.{action or 'unknown'}",
                    target_type="user",
                    target_id=email or None,
                    payload_summary={"email": email},
                    result="error",
                )
            return redirect(url_for("admin_users", status=status))

        query = request.args.get("q", "")
        return Response(
            render_template(
                "admin/users.html",
                page_title="Admin Users",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                status=request.args.get("status", ""),
                query=query,
                user_rows=access_store.list_users(query=query, limit=100),
            ),
            mimetype="text/html",
        )

    @app.route("/admin/grant", methods=["GET", "POST"])
    def admin_grant() -> Response:
        access_context = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "grant")
            email = request.form.get("email", "")
            try:
                if action == "revoke":
                    access_store.revoke_plan(email=email)
                    status = "revoked"
                else:
                    access_store.grant_plan(
                        email=email,
                        plan_id=request.form.get("plan_id", "free"),
                        expires_at=request.form.get("expires_at", "").strip() or None,
                    )
                    status = "granted"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.grant.{action}",
                    target_type="subscription",
                    target_id=email,
                    payload_summary={
                        "email": email,
                        "plan_id": request.form.get("plan_id", "free"),
                        "expires_at": request.form.get("expires_at", ""),
                    },
                    result="success",
                )
            except GrantValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.grant.{action}",
                    target_type="subscription",
                    target_id=email or None,
                    payload_summary={
                        "email": email,
                        "plan_id": request.form.get("plan_id", "free"),
                    },
                    result="error",
                )
            return redirect(url_for("admin_grant", status=status))

        return Response(
            render_template(
                "admin/grant.html",
                page_title="Admin Grant",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                status=request.args.get("status", ""),
                plan_rows=access_store.list_plans(),
            ),
            mimetype="text/html",
        )

    @app.route("/admin/plans-entitlements", methods=["GET", "POST"])
    def admin_plans_entitlements() -> Response:
        access_context = require_admin_access()
        if request.method == "POST":
            require_csrf()
            try:
                updated = access_store.update_plan_entitlement(
                    plan_id=request.form.get("plan_id", ""),
                    entitlement_key=request.form.get("entitlement_key", ""),
                    value_json=request.form.get("value_json", ""),
                )
                provider.load_bundle(force_refresh=True)
                status = "updated"
                audit_admin(
                    access_context=access_context,
                    action_type="admin.entitlements.update",
                    target_type="plan_entitlement",
                    target_id=f"{updated['plan_id']}:{updated['entitlement_key']}",
                    payload_summary=updated,
                    result="success",
                )
            except AdminValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type="admin.entitlements.update",
                    target_type="plan_entitlement",
                    target_id=None,
                    payload_summary={
                        "plan_id": request.form.get("plan_id", ""),
                        "entitlement_key": request.form.get("entitlement_key", ""),
                    },
                    result="error",
                )
            return redirect(url_for("admin_plans_entitlements", status=status))

        return Response(
            render_template(
                "admin/plans_entitlements.html",
                page_title="Plans & Entitlements",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                status=request.args.get("status", ""),
                plan_rows=access_store.list_plans(),
                entitlement_rows=access_store.list_plan_entitlement_rows(),
            ),
            mimetype="text/html",
        )

    @app.route("/admin/publish-snapshots", methods=["GET", "POST"])
    def admin_publish_snapshots() -> Response:
        access_context = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "refresh")
            try:
                if action == "activate":
                    label = request.form.get("snapshot_label", "")
                    activate_snapshot_label(label)
                    status = "activated"
                    audit_admin(
                        access_context=access_context,
                        action_type="admin.snapshots.activate",
                        target_type="snapshot",
                        target_id=label,
                        payload_summary={"snapshot_label": label},
                        result="success",
                    )
                else:
                    provider.load_bundle(force_refresh=True)
                    status = "refreshed"
                    audit_admin(
                        access_context=access_context,
                        action_type="admin.snapshots.refresh",
                        target_type="cache",
                        target_id="current",
                        payload_summary={"refresh": True},
                        result="success",
                    )
            except (AdminValidationError, SnapshotLoadError):
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.snapshots.{action}",
                    target_type="snapshot",
                    target_id=request.form.get("snapshot_label") or None,
                    payload_summary={"snapshot_label": request.form.get("snapshot_label", "")},
                    result="error",
                )
            return redirect(url_for("admin_publish_snapshots", status=status))

        return Response(
            render_template(
                "admin/publish_snapshots.html",
                page_title="Publish & Snapshots",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                status=request.args.get("status", ""),
                status_snapshot=provider.get_status(force_refresh=False),
                published_rows=build_published_snapshot_rows(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p1")
    def admin_preview_root() -> Response:
        require_internal_preview_access()
        return redirect(url_for("admin_preview_today_model_info"))

    @app.get("/admin/analytics-p1/today-model-info")
    def admin_preview_today_model_info() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewLoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_links(),
                    preview_title="오늘의 모델 정보 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_today_model_view(model)
            for model in preview_bundle.today_model_info.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_today.html",
                page_title="오늘의 모델 정보 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p1/model-changes")
    def admin_preview_model_changes() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewLoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_links(),
                    preview_title="모델 변화 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_change_model_view(model)
            for model in preview_bundle.model_changes.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_changes.html",
                page_title="모델 변화 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p1/model-compare")
    def admin_preview_model_compare() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewLoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_links(),
                    preview_title="모델 비교 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        compare_rows = [
            _build_preview_compare_row(row) for row in preview_bundle.model_compare.get("rows", [])
        ]
        return Response(
            render_template(
                "analytics_preview_compare.html",
                page_title="모델 비교 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_links(),
                preview_bundle=preview_bundle,
                compare_rows=compare_rows,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p2")
    def admin_preview_p2_root() -> Response:
        require_internal_preview_access()
        return redirect(url_for("admin_preview_portfolio_structure"))

    @app.get("/admin/analytics-p2/portfolio-structure")
    def admin_preview_portfolio_structure() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p2_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP2LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p2_links(),
                    preview_title="포트폴리오 구조 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_portfolio_structure_view(model)
            for model in preview_bundle.portfolio_structure.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_portfolio_structure.html",
                page_title="포트폴리오 구조 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p2_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p2/holding-lifecycle")
    def admin_preview_holding_lifecycle() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p2_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP2LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p2_links(),
                    preview_title="보유 종목 이력 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_holding_lifecycle_view(model)
            for model in preview_bundle.holding_lifecycle.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_holding_lifecycle.html",
                page_title="보유 종목 이력 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p2_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/feedback")
    def admin_feedback() -> Response:
        require_admin_access()
        feedback_rows = safe_list_recent_feedback(limit=100)
        metrics_summary = safe_metrics_summary()
        return Response(
            render_template(
                "admin/feedback.html",
                page_title="Admin Feedback",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                feedback_rows=feedback_rows,
                metrics_summary=metrics_summary,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/metrics")
    def admin_metrics() -> Response:
        require_admin_access()
        return Response(
            render_template(
                "admin/metrics.html",
                page_title="Admin Metrics",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                metrics_summary=safe_metrics_summary(),
                dashboard_summary=access_store.get_dashboard_summary(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/audit")
    def admin_audit() -> Response:
        require_admin_access()
        return Response(
            render_template(
                "admin/audit.html",
                page_title="Admin Audit",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                audit_rows=access_store.list_recent_audit_logs(limit=200),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/billing")
    def admin_billing() -> Response:
        require_admin_access()
        ensure_billing_enabled()
        return Response(
            render_template(
                "admin/billing.html",
                page_title="Admin Billing",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(),
                order_rows=access_store.list_recent_orders(limit=100),
                payment_event_rows=access_store.list_recent_payment_events(limit=100),
                subscription_rows=access_store.list_recent_subscriptions(limit=100),
            ),
            mimetype="text/html",
        )

    @app.get("/status")
    def status() -> Response:
        force_refresh = request.args.get("refresh") == "1"
        status_snapshot = user_snapshot_api.get_status(force_refresh=force_refresh)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        publish_status_payload = None
        if status_snapshot.snapshot_accessible:
            publish_status_payload = user_snapshot_api.get_publish_status(
                force_refresh=force_refresh
            )
        return Response(
            render_template(
                "status.html",
                page_title="서비스 상태",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                publish_status_payload=publish_status_payload,
            ),
            mimetype="text/html",
        )

    @app.get("/healthz")
    @app.get("/health")
    def healthz() -> tuple[dict[str, object], int]:
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        return (
            jsonify(
                {
                    "status": "ok",
                    "app_env": settings.app_env,
                    "snapshot_state": status_snapshot.state,
                    "snapshot_accessible": status_snapshot.snapshot_accessible,
                    "as_of_date": status_snapshot.as_of_date,
                    "generated_at": status_snapshot.generated_at,
                    "age_seconds": status_snapshot.age_seconds,
                    "feedback_submissions_24h": metrics_summary["feedback_submissions"],
                    "billing_enabled": settings.billing_enabled,
                    "market_analysis_state": market_analysis_api.get_status(
                        force_refresh=False
                    ).state,
                }
            ),
            200,
        )

    return app


if __name__ == "__main__":
    app = create_app()
    current_settings = app.config["SETTINGS"]
    app.run(host=current_settings.web_host, port=current_settings.web_port)
