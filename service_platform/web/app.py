from __future__ import annotations

import json
import secrets
import shutil
from copy import deepcopy
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
from service_platform.feedback.storage import FeedbackStore
from service_platform.shared.config import Settings, get_settings
from service_platform.shared.constants import CURRENT_DIRNAME, MANIFEST_FILENAME, PUBLISHED_DIRNAME
from service_platform.shared.email_delivery import (
    EmailDeliveryError,
    send_login_verification_email,
)
from service_platform.shared.logging import configure_logging
from service_platform.shared.notifications import send_alert
from service_platform.web.admin_market_lab_api import (
    AdminMarketLabApi,
    AdminMarketLabLoadError,
)
from service_platform.web.admin_new_entries_api import (
    EVENT_TYPE_OPTIONS_BY_SCOPE,
    INTERNAL_SCOPE_MODELS,
    TSERIES_SCOPE_MODELS,
    USER_SCOPE_MODELS,
    AdminNewEntriesApi,
)
from service_platform.web.analytics_preview_api import (
    AnalyticsPreviewApi,
    AnalyticsPreviewLoadError,
)
from service_platform.web.analytics_preview_p2_api import (
    AnalyticsPreviewP2Api,
    AnalyticsPreviewP2LoadError,
)
from service_platform.web.analytics_preview_p3_api import (
    AnalyticsPreviewP3Api,
    AnalyticsPreviewP3LoadError,
)
from service_platform.web.analytics_preview_p4_api import (
    AnalyticsPreviewP4Api,
    AnalyticsPreviewP4LoadError,
)
from service_platform.web.analytics_preview_p5_api import (
    AnalyticsPreviewP5Api,
    AnalyticsPreviewP5LoadError,
)
from service_platform.web.data_provider import SnapshotDataProvider, SnapshotLoadError
from service_platform.web.internal_models_api import (
    INTERNAL_ADMIN_MODEL_CODES,
    InternalModelsApi,
)
from service_platform.web.investment_portfolio_api import (
    InvestmentPortfolioApi,
    InvestmentPortfolioLoadError,
)
from service_platform.web.investment_status_api import (
    INVESTMENT_ACCOUNT_LABELS,
    InvestmentStatusService,
    InvestmentValidationError,
)
from service_platform.web.market_analysis_api import MarketAnalysisLoadError, MarketAnalysisMockApi
from service_platform.web.status_routes import register_status_routes
from service_platform.web.trading_sign_api import (
    TradingSignLoadError,
    TradingSignSnapshotApi,
    TradingSignStatus,
)
from service_platform.web.tseries_api import TSeriesLoadError, TSeriesOperationalApi
from service_platform.web.user_snapshot_api import UserSnapshotLoadError, UserSnapshotMockApi
from service_platform.web.valuation_ai_api import ValuationAiApi

STATUS_MESSAGES = {
    "invalid": "이메일 또는 비밀번호를 다시 확인해 주세요.",
    "signup_success": "회원가입이 완료되었습니다. 로그인해 주세요.",
    "code_sent": "휴대폰 인증번호를 발급했습니다.",
    "email_code_sent": "보안을 위해 이메일 인증번호를 확인해 주세요.",
    "email_code_invalid": "이메일 인증번호를 다시 확인해 주세요.",
    "email_code_expired": "이메일 인증 시간이 만료되었습니다. 다시 로그인해 주세요.",
    "email_send_error": "이메일 인증번호를 발송하지 못했습니다. 잠시 후 다시 시도해 주세요.",
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
INVESTMENT_MESSAGES = {
    "validated": "종목코드와 종목명이 확인되었습니다.",
    "saved": "거래가 저장되었습니다.",
    "updated": "거래내역이 수정되었습니다.",
    "security_mismatch": "종목코드와 종목명이 일치하지 않습니다.",
    "insufficient_holdings": "보유 수량보다 많은 매도는 저장할 수 없습니다.",
    "invalid": "입력값을 다시 확인해 주세요.",
}
T_SERIES_BUCKET_LABELS = {
    "confirmed": "우선 후보",
    "near": "근접 후보",
    "observe": "관찰 후보",
    "historical_stage1": "기존 1단계",
    "historical_stage2": "기존 2단계",
}
T_SERIES_ASSET_SCOPE_LABELS = {"stock": "주식", "etf": "ETF"}
T_SERIES_ETF_ROLE_LABELS = {
    "CORE_BETA": "핵심지수형",
    "STYLE_FACTOR": "스타일/팩터형",
    "SECTOR_THEME": "섹터/테마형",
    "DEFENSIVE_HEDGE": "방어/헤지형",
    "TACTICAL_HEDGE": "전술 헤지형",
    "TACTICAL_LEVERAGE": "전술 레버리지형",
    "UNCLASSIFIED": "미분류",
}
T_SERIES_WATCH_STATUS_LABELS = {"new": "신규", "active": "유지", "cooling": "쿨링"}
T_SERIES_WATCH_TIER_LABELS = {"core": "핵심", "monitor": "관찰"}
MARKET_ANALYSIS_DATA_TABS = (
    {"key": "state", "label": "시장 상태", "description": "상태점수와 구성요소 흐름"},
    {"key": "assets", "label": "자산 강도", "description": "자산군 상대강도와 20일 수익률"},
    {"key": "live", "label": "장중/야간 참고", "description": "장중 흐름과 야간 참고 레이어"},
    {"key": "guide", "label": "데이터 해설", "description": "지표 의미와 데이터 성격"},
)
PUBLIC_SERVICE_PROFILES = ("stable", "balanced", "growth")
PUBLIC_SERVICE_PROFILE_SET = set(PUBLIC_SERVICE_PROFILES)
USER_MODEL_LABELS = {"stable": "안정형", "balanced": "균형형", "growth": "성장형"}
TRADING_SIGN_MODEL_CODE_BY_PROFILE = {
    "stable": "STABLE",
    "balanced": "BALANCED",
    "growth": "GROWTH",
}
T_SERIES_TRADING_SIGN_MODEL_CODE_BY_MODEL = {
    "T-STOCK-V01": "T_STOCK_DISCOVERY",
    "T-ETF-V01": "T_ETF_DISCOVERY",
}
TRADING_SIGN_STATE_TONE_BY_LABEL = {
    "매수": "buy",
    "보유": "hold",
    "주의": "caution",
    "매도": "sell",
    "매수 대기": "wait",
}
TRADING_SIGN_STATE_SORT_ORDER = {
    "매수": 0,
    "보유": 1,
    "주의": 2,
    "매도": 3,
    "매수 대기": 4,
}
TRADING_SIGN_BLOCK_TITLE = "매매 신호(전일 종가 기준)"
AUTO_ADMIN_EMAILS = {"hrchoi@koreascf.com"}
AUTO_OPS_VIEWER_EMAILS = {"hrchoi@koreascf.com"}
# Ops viewer only accounts (admin 권한 자동 회수가 필요한 계정만 명시)
AUTO_OPS_VIEWER_ONLY_EMAILS: set[str] = set()

TRADING_SIGN_FALLBACK_TEXT = (
    "일간 신호 데이터가 아직 준비되지 않았습니다. 다음 갱신 후 다시 확인해 주세요."
)
TRADING_SIGN_DISCOVERY_FALLBACK_TEXT = (
    "상승종목 발굴 일간 신호 데이터가 아직 준비되지 않았습니다. 다음 갱신 후 다시 확인해 주세요."
)
DEFAULT_NEXT_DAY_PREVIEW_NOTICE = (
    "이 내용은 내일 시장을 참고용으로 정리한 공개 브리핑이며, 특정 매매행동을 안내하지 않습니다."
)
NEXT_DAY_PREVIEW_ASSET_LABELS = {
    "KOSPI200_NIGHT_FUT": "국내 야간선물",
    "KOREA_PROXY_EWY": "미국 상장 한국 ETF",
    "SP500_FUT": "S&P500 선물",
    "NASDAQ100_FUT": "나스닥100 선물",
    "USDKRW": "원달러",
    "WTI": "WTI",
    "US10Y": "미국 10년 금리",
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


def _is_public_service_profile(profile: Any) -> bool:
    return str(profile or "").strip().lower() in PUBLIC_SERVICE_PROFILE_SET


def _filter_public_profile_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in (rows or []) if _is_public_service_profile(row.get("service_profile"))]


def _filter_public_payload_list(payload: dict[str, Any], key: str) -> dict[str, Any]:
    filtered = deepcopy(payload or {})
    filtered[key] = _filter_public_profile_rows(filtered.get(key) or [])
    summary = filtered.get("summary")
    if isinstance(summary, dict) and "model_count" in summary:
        summary["model_count"] = len(filtered[key])
    if key == "reports":
        filtered["model_count"] = len(filtered[key])
    return filtered


def _filter_public_change_history(payload: dict[str, Any]) -> dict[str, Any]:
    filtered = deepcopy(payload or {})
    for period_key in ("weekly", "monthly"):
        period_rows = []
        for row in filtered.get(period_key) or []:
            if not isinstance(row, dict):
                continue
            period_row = dict(row)
            period_row["models"] = _filter_public_profile_rows(period_row.get("models") or [])
            period_rows.append(period_row)
        filtered[period_key] = period_rows
    history_rows = []
    for row in filtered.get("history") or []:
        if not isinstance(row, dict):
            continue
        history_row = dict(row)
        history_row["changes"] = _filter_public_profile_rows(history_row.get("changes") or [])
        history_rows.append(history_row)
    filtered["history"] = history_rows
    return filtered


def _filter_public_user_bundle(bundle: Any) -> Any:
    filtered = deepcopy(bundle)
    filtered.user_models = _filter_public_payload_list(filtered.user_models, "models")
    filtered.recommendation_today = _filter_public_payload_list(
        filtered.recommendation_today, "reports"
    )
    filtered.performance_summary = _filter_public_payload_list(
        filtered.performance_summary, "models"
    )
    filtered.recent_changes = _filter_public_payload_list(filtered.recent_changes, "changes")
    filtered.change_history = _filter_public_change_history(filtered.change_history)
    return filtered


def _normalize_change_model_filter(model: str | None) -> str:
    raw = str(model or "").strip().lower()
    aliases = {
        "stable": "stable",
        "안정형": "stable",
        "balanced": "balanced",
        "균형형": "balanced",
        "growth": "growth",
        "성장형": "growth",
    }
    return aliases.get(raw, raw)


def _filter_change_rows_by_model(
    rows: list[dict[str, Any]], model: str | None
) -> list[dict[str, Any]]:
    normalized_model = _normalize_change_model_filter(model)
    if not normalized_model:
        return rows
    return [
        row
        for row in rows
        if str(row.get("service_profile") or "").strip().lower() == normalized_model
        or str(row.get("user_model_name") or "").strip().lower() == normalized_model
    ]


def _build_change_history_rows(
    payload: dict[str, Any],
    *,
    period: str = "weekly",
    model: str | None = None,
) -> list[dict[str, Any]]:
    selected_period = period if period in {"weekly", "monthly"} else "weekly"
    source_rows = payload.get(selected_period) or []
    if not source_rows and selected_period == "weekly":
        source_rows = payload.get("history") or []
    history_rows: list[dict[str, Any]] = []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        raw_changes = row.get("models") if "models" in row else row.get("changes")
        changes = [change for change in (raw_changes or []) if isinstance(change, dict)]
        changes = _filter_change_rows_by_model(changes, model)
        if not changes:
            continue
        increase_count = sum(len(change.get("increase_items") or []) for change in changes)
        decrease_count = sum(len(change.get("decrease_items") or []) for change in changes)
        period_key = row.get("period_key") or row.get("change_date") or row.get("as_of_date") or "-"
        if selected_period == "monthly":
            summary = row.get("summary") or "월간 공개 모델 변경내역"
            date_label = period_key
            if row.get("start_date") and row.get("end_date"):
                date_label = f"{period_key} ({row.get('start_date')} ~ {row.get('end_date')})"
        else:
            summary = row.get("summary") or "주간 공개 모델 변경내역"
            date_label = period_key
        history_rows.append(
            {
                "change_date": date_label,
                "period_key": period_key,
                "period_type": selected_period,
                "summary": summary,
                "model_count": len(changes),
                "increase_count": increase_count,
                "decrease_count": decrease_count,
                "changes": changes,
            }
        )
    return sorted(history_rows, key=lambda item: str(item.get("change_date") or ""), reverse=True)


def _apply_public_status_counts(status_snapshot: Any, bundle: Any) -> Any:
    if status_snapshot is None or bundle is None:
        return status_snapshot
    status_snapshot.model_count = len(bundle.user_models.get("models", []))
    status_snapshot.report_count = len(bundle.recommendation_today.get("reports", []))
    return status_snapshot


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


def _format_market_kst_label(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]} KST"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text} KST"
    return _format_kst_datetime(text)


def _format_chart_date_label(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[5:10]
    return text


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


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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
            merged_item["rank_no"] = _safe_int(item.get("rank_no"))
            merged_item["strategy_fit_score"] = _safe_float(item.get("strategy_fit_score"))
            merged_item["strategy_fit_score_basis"] = str(
                item.get("strategy_fit_score_basis") or ""
            ).strip()
            merged_item["target_weight"] = weight
            merged[key] = merged_item
            continue
        merged_item["target_weight"] = float(merged_item.get("target_weight") or 0) + weight
        if not merged_item.get("role_summary") and item.get("role_summary"):
            merged_item["role_summary"] = item.get("role_summary")
        item_rank_no = _safe_int(item.get("rank_no"))
        current_rank_no = _safe_int(merged_item.get("rank_no"))
        if item_rank_no is not None and (current_rank_no is None or item_rank_no < current_rank_no):
            merged_item["rank_no"] = item_rank_no
        item_fit_score = _safe_float(item.get("strategy_fit_score"))
        current_fit_score = _safe_float(merged_item.get("strategy_fit_score"))
        if item_fit_score is not None and (
            current_fit_score is None or item_fit_score > current_fit_score
        ):
            merged_item["strategy_fit_score"] = item_fit_score
        if (
            not str(merged_item.get("strategy_fit_score_basis") or "").strip()
            and str(item.get("strategy_fit_score_basis") or "").strip()
        ):
            merged_item["strategy_fit_score_basis"] = str(
                item.get("strategy_fit_score_basis")
            ).strip()
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


def _build_today_performance_chart_view(period_view: dict[str, Any] | None) -> dict[str, Any]:
    ordered_rows = list((period_view or {}).get("ordered") or [])
    if not ordered_rows:
        return {"enabled": False, "line_series": [], "bar_series": []}

    line_series: list[dict[str, Any]] = []
    bar_series: list[dict[str, Any]] = []
    for row in ordered_rows:
        period_label = str(row.get("period") or "").strip()
        if not period_label or period_label in REFERENCE_PERIODS:
            continue
        headline_value = row.get("headline_value")
        if headline_value is None:
            headline_value = row.get("cagr")
        if headline_value is not None:
            line_series.append({"label": period_label, "value": headline_value})
        if row.get("mdd") is not None:
            bar_series.append({"label": period_label, "value": row.get("mdd")})

    return {
        "enabled": bool(line_series or bar_series),
        "line_series": line_series,
        "bar_series": bar_series,
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
    row_view["redesign_chart_view"] = _build_today_performance_chart_view(period_view)
    return row_view


def _build_trading_sign_section_view(
    section: dict[str, Any],
    *,
    include_empty: bool = True,
) -> dict[str, Any] | None:
    signals = []
    for row in section.get("signals") or []:
        signals.append(
            {
                "ticker": str(row.get("ticker") or "").strip(),
                "security_name": str(row.get("security_name") or "-").strip() or "-",
                "current_state": str(row.get("current_state") or "-").strip() or "-",
                "reason_summary": str(row.get("reason_summary") or "-").strip() or "-",
                "latest_state_change_date": str(row.get("latest_state_change_date") or "-").strip()
                or "-",
            }
        )
    signals.sort(
        key=lambda row: (
            TRADING_SIGN_STATE_SORT_ORDER.get(row["current_state"], 99),
            row["latest_state_change_date"],
            row["security_name"],
        )
    )
    if not include_empty and not signals:
        return None
    return {
        "section_key": str(section.get("section_key") or "").strip(),
        "title": str(section.get("title") or "일간 신호").strip(),
        "record_count": int(section.get("record_count") or len(signals)),
        "signals": signals,
    }


def _build_trading_sign_view(
    service_profile: str,
    model_detail: dict[str, Any] | None,
    status_snapshot: TradingSignStatus,
    *,
    fallback_message: str = TRADING_SIGN_FALLBACK_TEXT,
    preferred_section_keys: tuple[str, ...] | None = None,
    include_empty_sections: bool = True,
) -> dict[str, Any]:
    if status_snapshot.state in {"error", "empty"}:
        return {
            "enabled": False,
            "show_fallback": True,
            "fallback_message": fallback_message,
        }

    if not model_detail:
        return {
            "enabled": False,
            "show_fallback": True,
            "fallback_message": fallback_message,
        }

    ui_block = model_detail.get("ui_block") or {}
    if not ui_block:
        return {
            "enabled": False,
            "show_fallback": True,
            "fallback_message": fallback_message,
        }

    state_chips = []
    for chip in ui_block.get("state_chips") or []:
        state = str(chip.get("state") or "").strip()
        state_chips.append(
            {
                "state": state,
                "count": int(chip.get("count") or 0),
                "tone": TRADING_SIGN_STATE_TONE_BY_LABEL.get(state, "wait"),
            }
        )

    raw_sections = [
        section for section in (ui_block.get("sections") or []) if isinstance(section, dict)
    ]
    sections_by_key = {
        str(section.get("section_key") or "").strip(): section for section in raw_sections
    }
    ordered_sections: list[dict[str, Any]] = []
    if preferred_section_keys:
        for key in preferred_section_keys:
            section = sections_by_key.pop(key, None)
            if section is not None:
                ordered_sections.append(section)
    ordered_sections.extend(
        raw_sections if not preferred_section_keys else sections_by_key.values()
    )

    sections = []
    for section in ordered_sections:
        section_view = _build_trading_sign_section_view(
            section,
            include_empty=include_empty_sections,
        )
        if section_view is not None:
            sections.append(section_view)

    if not sections:
        return {
            "enabled": False,
            "show_fallback": True,
            "fallback_message": fallback_message,
        }

    stale_notice = ""
    if status_snapshot.state == "stale":
        stale_notice = "일간 신호 데이터 업데이트가 지연되어 최근 기준 스냅샷을 표시합니다."

    return {
        "enabled": True,
        "show_fallback": False,
        # Keep the public title stable even if upstream snapshot text lags behind.
        "title": TRADING_SIGN_BLOCK_TITLE,
        "description": str(ui_block.get("description") or "").strip(),
        "disclaimer": str(ui_block.get("disclaimer") or "").strip(),
        "signal_date": str(ui_block.get("signal_date") or "").strip(),
        "data_asof_date": str(ui_block.get("data_asof_date") or "").strip(),
        "generated_at": str(
            ui_block.get("generated_at") or status_snapshot.generated_at or ""
        ).strip(),
        "profile_code": str(ui_block.get("profile_code") or service_profile).strip(),
        "state_chips": state_chips,
        "sections": sections,
        "stale_notice": stale_notice,
    }


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


MARKET_STATE_LABEL_SCORES = {
    "강하락": -2.5,
    "하락": -1.5,
    "약보합": -0.5,
    "중립": 0.0,
    "강보합": 0.5,
    "상승": 1.5,
    "강상승": 2.5,
    "강세": 2.0,
    "소폭 강세": 0.8,
    "혼조": 0.0,
    "약세": -1.2,
    "강한 약세": -2.4,
    "전일 기준 참고": 0.0,
}


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


def _market_state_score_from_label(label: Any) -> float | None:
    normalized = str(label or "").strip()
    if not normalized:
        return None
    return MARKET_STATE_LABEL_SCORES.get(normalized)


def _build_market_state_label_bar(
    *,
    title: str,
    state_label: Any,
    asof: str | None,
) -> dict[str, Any]:
    normalized_label = str(state_label or "").strip() or "데이터 준비 중"
    score = _market_state_score_from_label(normalized_label)
    return {
        "title": str(title or "시장상태").strip() or "시장상태",
        "label": normalized_label,
        "score": score,
        "position_percent": _market_score_percent(score),
        "asof_display": _format_kst_datetime(asof),
    }


def _build_market_state_bridge_view(
    bridge_payload: dict[str, Any] | None,
    *,
    fallback_bar: dict[str, Any],
    asof: str | None,
) -> dict[str, Any]:
    payload = bridge_payload or {}
    # Keep dual-layer UI resilient when upstream sends bridge payload without intraday label.
    has_bridge_payload = bool(payload)
    enabled = payload.get("enabled") is True or has_bridge_payload
    medium_term_state_label = (
        str(
            payload.get("medium_term_state_label") or fallback_bar.get("label") or "데이터 준비 중"
        ).strip()
        or "데이터 준비 중"
    )
    intraday_state_label = str(payload.get("intraday_state_label") or "").strip()
    if not intraday_state_label and has_bridge_payload:
        intraday_state_label = "전일 기준 참고"
    basis_lines = [
        str(line).strip() for line in (payload.get("basis_lines") or []) if str(line).strip()
    ]
    return {
        "enabled": enabled,
        "alignment": str(payload.get("alignment") or "").strip(),
        "display_label": str(payload.get("display_label") or "").strip(),
        "bridge_text": str(payload.get("bridge_text") or "").strip(),
        "basis_lines": basis_lines[:2],
        "medium_term_bar": _build_market_state_label_bar(
            title=str(payload.get("medium_term_label") or "퀀트모델 시장 흐름").strip(),
            state_label=medium_term_state_label,
            asof=asof,
        ),
        "medium_term_description": str(payload.get("medium_term_description") or "").strip(),
        "intraday_bar": (
            _build_market_state_label_bar(
                title=str(payload.get("intraday_label") or "오늘 장중 흐름").strip(),
                state_label=intraday_state_label,
                asof=asof,
            )
            if intraday_state_label
            else None
        ),
        "intraday_description": str(payload.get("intraday_description") or "").strip(),
        "fallback_bar": fallback_bar,
        "asof_display": fallback_bar.get("asof_display") or _format_kst_datetime(asof),
    }


def _format_market_metric(value: Any, unit: str = "", *, signed: bool = False) -> str:
    numeric = _coerce_market_score(value)
    if numeric is None:
        return "데이터 확인 중"
    prefix = "+" if signed and numeric > 0 else ""
    if abs(numeric) >= 1000:
        text = f"{numeric:,.0f}"
    elif abs(numeric) >= 100:
        text = f"{numeric:,.1f}"
    else:
        text = f"{numeric:,.2f}".rstrip("0").rstrip(".")
    return f"{prefix}{text}{unit}"


def _market_gauge_percent(value: Any) -> float:
    numeric = _coerce_market_score(value)
    if numeric is None:
        return 50.0
    return max(0.0, min(100.0, numeric))


def _market_composite_axis_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    axes = payload.get("axes") if isinstance(payload.get("axes"), list) else []
    return {
        str(axis.get("axis_id") or "").strip(): axis
        for axis in axes
        if isinstance(axis, dict) and str(axis.get("axis_id") or "").strip()
    }


def _format_key_indicator_value(value: Any, unit: Any = "") -> str:
    unit_text = str(unit or "").strip()
    if value is None or value == "":
        return "데이터 확인 중"
    if unit_text == "label":
        return str(value).strip() or "데이터 확인 중"
    suffix = "" if unit_text in {"score", "pt"} else unit_text
    return _format_market_metric(value, suffix)


def _composite_chart_y(
    value: Any, *, chart_height: float, score_min: float, score_max: float
) -> float:
    numeric = _coerce_market_score(value)
    if numeric is None or score_max <= score_min:
        numeric = 0.0
    numeric = max(score_min, min(score_max, numeric))
    return round((score_max - numeric) / (score_max - score_min) * chart_height, 1)


def _market_score_state_label(value: Any) -> str:
    numeric = _coerce_market_score(value)
    if numeric is None:
        return "데이터 확인 중"
    if numeric <= -2.0:
        return "매우 나쁨"
    if numeric <= -1.0:
        return "나쁨"
    if numeric < -0.3:
        return "다소 나쁨"
    if numeric <= 0.3:
        return "중립"
    if numeric < 1.0:
        return "다소 좋음"
    if numeric < 2.0:
        return "좋음"
    return "매우 좋음"


def _build_market_composite_chart_view(chart: dict[str, Any]) -> dict[str, Any]:
    score_range = chart.get("score_range") if isinstance(chart.get("score_range"), dict) else {}
    y_axis = chart.get("y_axis") if isinstance(chart.get("y_axis"), dict) else {}
    neutral = chart.get("neutral_band") if isinstance(chart.get("neutral_band"), dict) else {}
    score_min = _coerce_market_score(score_range.get("min", y_axis.get("min", -3.0))) or -3.0
    score_max = _coerce_market_score(score_range.get("max", y_axis.get("max", 3.0))) or 3.0
    neutral_min = _coerce_market_score(neutral.get("min")) or -0.3
    neutral_max = _coerce_market_score(neutral.get("max")) or 0.3
    viewport_width = 720.0
    height = 280.0
    visible_points = 120
    chart_right_padding = 80.0
    raw_series_rows: list[dict[str, Any]] = []
    raw_reference_rows: list[dict[str, Any]] = []
    all_dates: list[str] = []
    next_day_signal_test_dates: set[str] = set()
    for raw_series in chart.get("series") or []:
        if not isinstance(raw_series, dict):
            continue
        raw_points = [p for p in (raw_series.get("points") or []) if isinstance(p, dict)]
        if not raw_points:
            continue
        point_by_date = {}
        for raw_point in raw_points:
            date_text = str(raw_point.get("date") or "").strip()
            if not date_text:
                continue
            if str(raw_point.get("point_role") or "").strip() == "next_day_signal_test":
                next_day_signal_test_dates.add(date_text)
            point_by_date[date_text] = raw_point
            all_dates.append(date_text)
        raw_series_rows.append(
            {
                "series_id": str(raw_series.get("series_id") or "").strip(),
                "label": str(raw_series.get("label") or "시장 지표").strip(),
                "color": str(raw_series.get("color") or "#64748b").strip(),
                "description": str(raw_series.get("description") or "").strip(),
                "latest_visual": (
                    raw_series.get("latest_visual")
                    if isinstance(raw_series.get("latest_visual"), dict)
                    else {}
                ),
                "point_by_date": point_by_date,
            }
        )
    for raw_reference in chart.get("reference_indices") or []:
        if not isinstance(raw_reference, dict):
            continue
        series_id = str(raw_reference.get("series_id") or "").strip()
        if series_id != "reference_index_kospi":
            continue
        raw_points = [p for p in (raw_reference.get("points") or []) if isinstance(p, dict)]
        if not raw_points:
            continue
        filtered_points = []
        previous_reference_value: float | None = None
        for raw_point in raw_points:
            reference_value = _coerce_market_score(
                raw_point.get("raw_close", raw_point.get("value"))
            )
            if (
                previous_reference_value
                and reference_value
                and abs(reference_value - previous_reference_value)
                / max(abs(previous_reference_value), 1.0)
                > 0.2
            ):
                continue
            filtered_points.append(raw_point)
            if reference_value:
                previous_reference_value = reference_value
        raw_points = filtered_points
        point_by_date = {}
        for raw_point in raw_points:
            date_text = str(raw_point.get("date") or "").strip()
            if not date_text:
                continue
            if str(raw_point.get("point_role") or "").strip() == "next_day_signal_test":
                next_day_signal_test_dates.add(date_text)
            point_by_date[date_text] = raw_point
            all_dates.append(date_text)
        raw_reference_rows.append(
            {
                "series_id": series_id,
                "label": str(raw_reference.get("label") or "주가지수 기준선").strip(),
                "color": "#374151",
                "description": str(raw_reference.get("description") or "").strip(),
                "unit": str(raw_reference.get("unit") or "").strip(),
                "base_date": str(raw_reference.get("base_date") or "").strip(),
                "base_value": raw_reference.get("base_value"),
                "latest_date": str(raw_reference.get("latest_date") or "").strip(),
                "latest_value": raw_reference.get("latest_value"),
                "latest_close": raw_reference.get("latest_close"),
                "point_by_date": point_by_date,
            }
        )
    unique_dates = sorted(set(all_dates))
    point_count = max(len(unique_dates) - 1, 1)
    width = max(
        viewport_width,
        round(point_count / max(visible_points - 1, 1) * viewport_width, 1),
    )
    content_width = width
    scroll_width = width + chart_right_padding
    date_to_x = {
        date_text: round(index / point_count * width, 1)
        for index, date_text in enumerate(unique_dates)
    }
    reference_values = [
        numeric
        for raw_reference in raw_reference_rows
        for raw_point in raw_reference["point_by_date"].values()
        if (numeric := _coerce_market_score(raw_point.get("value"))) is not None
    ]
    reference_min = min(reference_values) if reference_values else 0.0
    reference_max = max(reference_values) if reference_values else 1.0
    reference_padding = max((reference_max - reference_min) * 0.06, 1.0)
    reference_min -= reference_padding
    reference_max += reference_padding

    def _reference_chart_y(value: Any) -> float:
        numeric = _coerce_market_score(value)
        if numeric is None or reference_max <= reference_min:
            numeric = reference_min + ((reference_max - reference_min) / 2)
        numeric = max(reference_min, min(reference_max, numeric))
        return round((reference_max - numeric) / (reference_max - reference_min) * height, 1)

    series_rows = []
    tooltip_by_date: dict[str, dict[str, Any]] = {
        date_text: {"date": date_text, "label": _format_chart_date_label(date_text), "items": []}
        for date_text in unique_dates
    }
    for raw_series in raw_series_rows:
        points = []
        for date_text in unique_dates:
            raw_point = raw_series["point_by_date"].get(date_text)
            if not raw_point:
                continue
            score_value = raw_point.get("value")
            x_position = date_to_x[date_text]
            point_role = str(raw_point.get("point_role") or "").strip()
            is_next_day_signal_test = point_role == "next_day_signal_test"
            display_label = str(raw_point.get("display_label") or "").strip()
            preview_label = str(raw_point.get("preview_label") or "").strip()
            points.append(
                {
                    "x": x_position,
                    "y": _composite_chart_y(
                        score_value,
                        chart_height=height,
                        score_min=score_min,
                        score_max=score_max,
                    ),
                    "date": date_text,
                    "value": _format_market_metric(score_value),
                    "point_role": point_role,
                    "date_tone": str(raw_point.get("date_tone") or "").strip(),
                    "is_next_day_signal_test": is_next_day_signal_test,
                }
            )
            state_label = _market_score_state_label(score_value)
            if is_next_day_signal_test:
                test_label = display_label or "익일 신호 테스트"
                preview_text = f" · {preview_label}" if preview_label else ""
                official_text = (
                    "정식 점수 미반영"
                    if raw_point.get("official_score_impact") is False
                    else "정식 반영 여부 확인 필요"
                )
                state_label = f"{test_label}{preview_text} · 검증 전 실험값 · {official_text}"
            tooltip_by_date[date_text]["items"].append(
                {
                    "label": raw_series["label"],
                    "color": raw_series["color"],
                    "value": _format_market_metric(score_value),
                    "state": state_label,
                }
            )
        if not points:
            continue
        latest = raw_series["latest_visual"]
        latest_point = points[-1]
        latest_position = _market_gauge_percent(latest.get("position_pct"))
        series_rows.append(
            {
                "series_id": raw_series["series_id"],
                "label": raw_series["label"],
                "color": raw_series["color"],
                "description": raw_series["description"],
                "points": points,
                "polyline": " ".join(f"{p['x']},{p['y']}" for p in points),
                "latest": {
                    "x": latest_point["x"],
                    "y": latest_point["y"],
                    "display_text": str(
                        latest.get("display_text") or latest_point["value"]
                    ).strip(),
                    "position_pct": latest_position,
                    "band_label": str((latest.get("band") or {}).get("label") or "").strip(),
                    "explain_text": str(latest.get("explain_text") or "").strip(),
                },
            }
        )
    reference_index_rows = []
    for raw_reference in raw_reference_rows:
        points = []
        for date_text in unique_dates:
            raw_point = raw_reference["point_by_date"].get(date_text)
            if not raw_point:
                continue
            index_value = raw_point.get("value")
            raw_close = raw_point.get("raw_close", raw_reference.get("latest_close"))
            x_position = date_to_x[date_text]
            points.append(
                {
                    "x": x_position,
                    "y": _reference_chart_y(index_value),
                    "date": date_text,
                    "value": _format_market_metric(index_value),
                    "raw_close": _format_market_metric(raw_close),
                }
            )
            tooltip_by_date[date_text]["items"].append(
                {
                    "label": raw_reference["label"],
                    "color": raw_reference["color"],
                    "value": f"기준 {_format_market_metric(index_value)}",
                    "state": f"종가 {_format_market_metric(raw_close)}",
                }
            )
        if not points:
            continue
        latest_point = points[-1]
        latest_value = raw_reference.get("latest_value")
        latest_close = raw_reference.get("latest_close")
        reference_index_rows.append(
            {
                "series_id": raw_reference["series_id"],
                "label": raw_reference["label"],
                "color": raw_reference["color"],
                "description": raw_reference["description"],
                "unit": raw_reference["unit"],
                "base_date": raw_reference["base_date"],
                "base_value": _format_market_metric(raw_reference["base_value"]),
                "latest": {
                    "x": latest_point["x"],
                    "y": latest_point["y"],
                    "value": _format_market_metric(latest_value),
                    "close": _format_market_metric(latest_close),
                },
                "polyline": " ".join(f"{p['x']},{p['y']}" for p in points),
            }
        )
    date_labels = []
    if unique_dates:
        label_step = 20
        min_label_gap = 88.0
        label_indexes = set(range(0, len(unique_dates), label_step))
        label_indexes.update({0, len(unique_dates) - 1})
        for label_index in sorted(label_indexes):
            date_text = unique_dates[label_index]
            is_next_day_signal_test = date_text in next_day_signal_test_dates
            label_text = _format_chart_date_label(date_text)
            label_tone = "muted" if is_next_day_signal_test else ""
            if is_next_day_signal_test and label_index > 0:
                previous_date_text = unique_dates[label_index - 1]
                label_text = (
                    f"{_format_chart_date_label(previous_date_text)}"
                    f" -> {_format_chart_date_label(date_text)} 익일 테스트"
                )
            label = {
                "x": date_to_x[date_text],
                "label": label_text,
                "tone": label_tone,
                "is_next_day_signal_test": is_next_day_signal_test,
            }
            if date_labels and label["x"] - date_labels[-1]["x"] < min_label_gap:
                if label_index == len(unique_dates) - 1 and len(date_labels) > 1:
                    date_labels[-1] = label
                continue
            date_labels.append(label)
    hover_points = []
    for date_text in unique_dates:
        tooltip = tooltip_by_date.get(date_text) or {}
        if not tooltip.get("items"):
            continue
        hover_points.append(
            {
                "x": date_to_x[date_text],
                "width": max(6, round(width / max(len(unique_dates), 1), 1)),
                "height": height,
                "tooltip": tooltip,
            }
        )
    y_ticks = []
    for tick in (3.0, 1.5, 0.0, -1.5, -3.0):
        y_ticks.append(
            {
                "value": tick,
                "label": f"{tick:+.1f}".replace("+0.0", "0.0"),
                "y": _composite_chart_y(
                    tick, chart_height=height, score_min=score_min, score_max=score_max
                ),
            }
        )
    neutral_y_top = _composite_chart_y(
        neutral_max, chart_height=height, score_min=score_min, score_max=score_max
    )
    neutral_y_bottom = _composite_chart_y(
        neutral_min, chart_height=height, score_min=score_min, score_max=score_max
    )
    return {
        "enabled": bool(series_rows),
        "title": "시장흐름 3축 그래프",
        "subtitle": str(chart.get("subtitle") or "").strip(),
        "width": int(viewport_width),
        "scroll_width": int(scroll_width),
        "content_width": int(content_width),
        "height": int(height),
        "viewbox": f"0 0 {int(scroll_width)} {int(height)}",
        "score_min": score_min,
        "score_max": score_max,
        "neutral_band": {
            "label": str(neutral.get("label") or "중립권").strip(),
            "y": min(neutral_y_top, neutral_y_bottom),
            "height": abs(neutral_y_bottom - neutral_y_top),
        },
        "series": series_rows,
        "reference_indices": reference_index_rows,
        "date_labels": date_labels,
        "hover_points": hover_points,
        "y_ticks": y_ticks,
        "has_next_day_signal_test": bool(next_day_signal_test_dates),
    }


def _build_market_state_composite_view(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload or {}
    if source.get("enabled") is not True:
        return {"enabled": False}
    composite_chart = (
        source.get("composite_chart") if isinstance(source.get("composite_chart"), dict) else {}
    )
    chart_view = _build_market_composite_chart_view(composite_chart)
    key_indicators = (
        source.get("key_indicators") if isinstance(source.get("key_indicators"), dict) else {}
    )
    key_groups = []
    for group in key_indicators.get("groups") or []:
        if not isinstance(group, dict):
            continue
        key_groups.append(
            {
                "group_id": str(group.get("group_id") or "").strip(),
                "title": str(group.get("title") or "핵심지표").strip(),
                "items": [
                    {
                        "label": str(item.get("label") or "-").strip(),
                        "value": _format_key_indicator_value(item.get("value"), item.get("unit")),
                        "tone": str(item.get("tone") or "neutral").strip(),
                    }
                    for item in (group.get("items") or [])[:6]
                    if isinstance(item, dict)
                ],
            }
        )
    considerations = []
    for item in source.get("investment_considerations") or []:
        if not isinstance(item, dict):
            continue
        considerations.append(
            {
                "label": str(item.get("label") or "").strip(),
                "body": str(item.get("body") or "").strip(),
                "tone": str(item.get("tone") or "neutral").strip(),
                "basis": [str(v).strip() for v in (item.get("basis") or []) if str(v).strip()],
            }
        )
    score_scale = (
        source.get("score_scale_guide") if isinstance(source.get("score_scale_guide"), dict) else {}
    )
    score_bands = [
        {
            "label": str(item.get("label") or "").strip(),
            "range": str(item.get("range") or "").strip(),
            "tone": str(item.get("tone") or "neutral").strip(),
            "color": str(item.get("color") or "#94a3b8").strip(),
        }
        for item in (score_scale.get("bands") or [])
        if isinstance(item, dict)
    ]
    summary = source.get("summary") if isinstance(source.get("summary"), dict) else {}
    if str(source.get("schema_version") or "").strip() == "market_state_composite.v2":
        return {
            "enabled": bool(chart_view.get("enabled")),
            "layout": "multi_line",
            "title": "시장 현황판",
            "subtitle": str(source.get("subtitle") or "").strip(),
            "asof_display": _format_kst_datetime(source.get("asof")),
            "summary_line": str(summary.get("one_line") or "").strip(),
            "chart": chart_view,
            "key_indicators_title": str(key_indicators.get("title") or "핵심 판단 숫자").strip(),
            "key_indicator_groups": key_groups,
            "investment_considerations": considerations,
            "score_bands": score_bands,
            "interpretation_rules": [
                str(item).strip()
                for item in (source.get("interpretation_rules") or [])
                if str(item).strip()
            ],
        }
    axes = _market_composite_axis_lookup(source)
    environment = axes.get("financial_environment", {})
    medium_term = axes.get("medium_term_model_outlook", {})
    short_term = axes.get("short_term_market_condition", {})
    summary = source.get("summary") if isinstance(source.get("summary"), dict) else {}
    today = short_term.get("today") if isinstance(short_term.get("today"), dict) else {}
    weekly = short_term.get("weekly") if isinstance(short_term.get("weekly"), dict) else {}

    cards = [
        {
            "axis_id": "financial_environment",
            "title": str(environment.get("title") or "금융시장 환경").strip(),
            "subtitle": str(environment.get("subtitle") or "기회와 리스크").strip(),
            "label": str(environment.get("status_label") or "데이터 확인 중").strip(),
            "tone": str(environment.get("tone") or "neutral").strip(),
            "gauge_value": _market_gauge_percent(environment.get("gauge_value")),
            "score_text": _format_market_metric(environment.get("score")),
            "metrics": [
                {
                    "label": "기회",
                    "value": _format_market_metric(environment.get("opportunity_score")),
                },
                {
                    "label": "리스크",
                    "value": _format_market_metric(environment.get("risk_pressure_score")),
                },
            ],
            "key_numbers": [
                {
                    "label": str(item.get("label") or "-").strip(),
                    "value": _format_market_metric(item.get("value"), str(item.get("unit") or "")),
                }
                for item in (environment.get("key_numbers") or [])[:4]
                if isinstance(item, dict)
            ],
            "basis": [
                str(item).strip() for item in (environment.get("basis") or []) if str(item).strip()
            ][:2],
        },
        {
            "axis_id": "medium_term_model_outlook",
            "title": str(medium_term.get("title") or "퀀트모델 시장 전망").strip(),
            "subtitle": str(medium_term.get("subtitle") or "1~6개월 흐름").strip(),
            "label": str(medium_term.get("state_label") or "데이터 확인 중").strip(),
            "tone": str(medium_term.get("tone") or "neutral").strip(),
            "gauge_value": _market_gauge_percent(medium_term.get("gauge_value")),
            "score_text": _format_market_metric(medium_term.get("score")),
            "metrics": [
                {
                    "label": str(item.get("label") or "-").strip(),
                    "value": _format_market_metric(item.get("score")),
                }
                for item in (medium_term.get("components") or [])[:4]
                if isinstance(item, dict)
            ],
            "key_numbers": [
                {
                    "label": f"{str(item.get('market_scope') or '-').strip()} 20거래일",
                    "value": _format_market_metric(
                        item.get("predicted_forward_return_pct"), "%", signed=True
                    ),
                }
                for item in (medium_term.get("forecast_20d") or [])[:3]
                if isinstance(item, dict)
            ],
            "basis": [
                str(item).strip() for item in (medium_term.get("basis") or []) if str(item).strip()
            ][:2],
        },
        {
            "axis_id": "short_term_market_condition",
            "title": str(short_term.get("title") or "단기 시장 상황").strip(),
            "subtitle": str(short_term.get("subtitle") or "최근 1주일 + 오늘").strip(),
            "label": str(short_term.get("status_label") or "데이터 확인 중").strip(),
            "tone": str(short_term.get("tone") or "neutral").strip(),
            "gauge_value": _market_gauge_percent(short_term.get("gauge_value")),
            "score_text": _format_market_metric(short_term.get("score")),
            "metrics": [
                {
                    "label": "KOSPI 1주",
                    "value": _format_market_metric(
                        weekly.get("kospi_5d_ret_pct"), "%", signed=True
                    ),
                },
                {
                    "label": "KOSDAQ 1주",
                    "value": _format_market_metric(
                        weekly.get("kosdaq_5d_ret_pct"), "%", signed=True
                    ),
                },
                {
                    "label": "장중",
                    "value": str(today.get("intraday_state_label") or "데이터 확인 중"),
                },
                {
                    "label": "외국인",
                    "value": _format_market_metric(today.get("foreigner_net"), "억"),
                },
            ],
            "key_numbers": [
                {
                    "label": "선물",
                    "value": _format_market_metric(
                        today.get("futures_change_pct"), "%", signed=True
                    ),
                },
                {
                    "label": "프로그램",
                    "value": _format_market_metric(today.get("program_total_net"), "억"),
                },
            ],
            "basis": [
                str(item).strip() for item in (short_term.get("basis") or []) if str(item).strip()
            ][:2],
        },
    ]
    return {
        "enabled": True,
        "title": "시장 현황판",
        "subtitle": str(source.get("subtitle") or "").strip(),
        "asof_display": _format_kst_datetime(source.get("asof")),
        "summary_line": str(summary.get("one_line") or "").strip(),
        "cards": cards,
        "interpretation_rules": [
            str(item).strip()
            for item in (source.get("interpretation_rules") or [])
            if str(item).strip()
        ],
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

    def _strip_summary_prefix(value: str) -> str:
        for prefix in ("긍정:", "리스크:"):
            if value.startswith(prefix):
                return value[len(prefix) :].strip()
        return value

    for provider in providers:
        if not isinstance(provider, dict) or not provider.get("enabled"):
            continue
        summary_lines = [
            str(line).strip() for line in (provider.get("summary_lines") or []) if str(line).strip()
        ][:8]
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
        cleaned_lines = [_strip_summary_prefix(line) for line in summary_lines]
        split_index = 4 if len(summary_lines) == 8 else 3 if len(summary_lines) == 6 else 0
        split_enabled = split_index > 0
        cards.append(
            {
                "provider": provider_name,
                "label": provider_label,
                "full_title": full_title,
                "sort_order": sort_order,
                "source": provider.get("source") or "",
                "generated_at": provider.get("generated_at"),
                "summary_lines": cleaned_lines,
                "positive_lines": cleaned_lines[:split_index] if split_enabled else [],
                "risk_lines": cleaned_lines[split_index : split_index * 2] if split_enabled else [],
                "split_enabled": split_enabled,
            }
        )
    cards.sort(key=lambda item: (item.get("sort_order", 99), item.get("label", "")))
    show_placeholder = enabled and not cards
    return {
        "enabled": enabled,
        "title": title,
        "has_gemini": any(card.get("provider") == "gemini" for card in cards),
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
    ai_providers = (page_payload.get("ai_briefs") or {}).get("providers") or []
    generated_at = page_payload.get("generated_at")
    for provider in ai_providers:
        if isinstance(provider, dict) and provider.get("generated_at"):
            generated_at = provider.get("generated_at")
            break
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
    state_bar = _build_market_state_bar(
        label=header_state.get("label") or "데이터 준비 중",
        score=header_state.get("score"),
        prev_label=header_state.get("prev_label") or "-",
        change_direction=header_state.get("change_direction") or "unchanged",
        asof=page_payload.get("asof"),
    )
    return {
        "asof": page_payload.get("asof"),
        "as_of_date": _format_kst_datetime(page_payload.get("asof")),
        "generated_at": generated_at,
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
        "state_bar": state_bar,
        "market_state_composite_view": _build_market_state_composite_view(
            page_payload.get("market_state_composite")
        ),
        "state_intraday_bridge_view": _build_market_state_bridge_view(
            page_payload.get("state_intraday_bridge"),
            fallback_bar=state_bar,
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


def _build_market_timeline_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    points = payload.get("points") or []
    if points:
        return [point for point in points if isinstance(point, dict)]
    series = payload.get("series") or []
    normalized_points: list[dict[str, Any]] = []
    for row in series:
        if not isinstance(row, dict):
            continue
        total_score = row.get("total_score")
        normalized_points.append(
            {
                "asof": row.get("asof"),
                "state_label": row.get("state_label"),
                "state_score": total_score,
                "trend_score": row.get("trend_score"),
                "breadth_score": row.get("breadth_score"),
                "risk_score": row.get("risk_score"),
                "defensive_flow_score": row.get("defensive_flow_score"),
                "total_score": total_score,
            }
        )
    return normalized_points


def _build_market_timeline_view(payload: dict[str, Any]) -> dict[str, Any]:
    points = _build_market_timeline_points(payload)
    rows = []
    chart_series = []
    for point in points[-180:]:
        chart_series.append(
            {
                "label": _format_kst_datetime(point.get("asof")),
                "score": _coerce_market_score(point.get("total_score")),
            }
        )
    for row in points[-12:]:
        score = row.get("total_score")
        try:
            score_text = f"{float(score):.2f}"
        except (TypeError, ValueError):
            score_text = "-"
        rows.append(
            {
                "asof": row.get("asof"),
                "asof_display": _format_kst_datetime(row.get("asof")),
                "state_label": row.get("state_label") or "-",
                "score": row.get("total_score"),
                "score_text": score_text,
                "position_percent": _market_score_percent(
                    _coerce_market_score(row.get("total_score"))
                ),
            }
        )
    current_state = payload.get("current_state") or (points[-1] if points else {})
    return {
        "enabled": bool(payload and rows),
        "title": str(payload.get("title") or "상태 타임라인").strip(),
        "description": str(payload.get("description") or "").strip(),
        "trend_direction": MARKET_CHANGE_DIRECTION_LABELS.get(
            str(payload.get("trend_direction") or "unchanged"),
            "변화 없음",
        ),
        "current_state_label": current_state.get("state_label") or "-",
        "current_score_text": rows[-1]["score_text"] if rows else "-",
        "rows": rows,
        "chart_series": chart_series,
    }


def _latest_asset_strength_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets = payload.get("assets") or []
    if assets:
        return [row for row in assets if isinstance(row, dict)]
    series = [row for row in (payload.get("series") or []) if isinstance(row, dict)]
    latest_asof = ""
    for row in series:
        asof = str(row.get("asof") or "")
        if asof > latest_asof:
            latest_asof = asof
    if not latest_asof:
        return []
    latest_rows = [row for row in series if str(row.get("asof") or "") == latest_asof]
    return sorted(latest_rows, key=lambda row: _safe_float(row.get("strength_rank")) or 999)


def _build_market_asset_strength_view(payload: dict[str, Any]) -> dict[str, Any]:
    assets = []
    chart_bars = []
    raw_assets = _latest_asset_strength_rows(payload)
    for row in raw_assets:
        score_value = _safe_float(row.get("strength_score"))
        ret_value = _safe_float(row.get("ret_20d"))
        assets.append(
            {
                "asset_group": row.get("asset_group") or "-",
                "strength_rank": row.get("strength_rank") or "-",
                "strength_label": row.get("strength_label") or "-",
                "ret_20d_display": _format_percent(row.get("ret_20d")),
                "strength_score_display": (
                    f"{score_value:.2f}" if score_value is not None else "-"
                ),
            }
        )
        chart_bars.append(
            {
                "label": str(row.get("asset_group") or "-"),
                "score": score_value,
                "ret_20d": ret_value,
            }
        )
    top_assets = [
        str(item.get("asset_group") or "-") for item in (payload.get("top_assets") or [])[:2]
    ]
    bottom_assets = [
        str(item.get("asset_group") or "-") for item in (payload.get("bottom_assets") or [])[:2]
    ]
    if not top_assets:
        top_assets = [str(item.get("asset_group") or "-") for item in raw_assets[:2]]
    if not bottom_assets:
        bottom_assets = [str(item.get("asset_group") or "-") for item in raw_assets[-2:]]
    return {
        "enabled": bool(payload and assets),
        "title": str(payload.get("title") or "자산군 상대강도").strip(),
        "description": str(payload.get("description") or "").strip(),
        "assets": assets,
        "top_assets_text": ", ".join(top_assets) if top_assets else "-",
        "bottom_assets_text": ", ".join(bottom_assets) if bottom_assets else "-",
        "chart_bars": chart_bars,
    }


def _build_market_home_chart_view(
    timeline_payload: dict[str, Any] | None,
    asset_strength_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    timeline_view = _build_market_timeline_view(timeline_payload or {})
    asset_strength_view = _build_market_asset_strength_view(asset_strength_payload or {})
    return {
        "enabled": bool(timeline_view.get("enabled") or asset_strength_view.get("enabled")),
        "timeline": timeline_view,
        "asset_strength": asset_strength_view,
    }


def _build_market_state_transition_view(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload.get("current") or {}
    recent_changes = []
    for row in (payload.get("recent_changes") or [])[:8]:
        score = row.get("state_score")
        try:
            score_text = f"{float(score):.2f}"
        except (TypeError, ValueError):
            score_text = "-"
        recent_changes.append(
            {
                "asof_display": _format_kst_datetime(row.get("asof")),
                "state_label": row.get("state_label") or "-",
                "prev_state_label": row.get("prev_state_label") or "-",
                "direction_label": MARKET_CHANGE_DIRECTION_LABELS.get(
                    str(row.get("state_change_direction") or "unchanged"),
                    "변화 없음",
                ),
                "score_text": score_text,
            }
        )
    duration_hours = current.get("duration_hours")
    duration_text = f"{float(duration_hours):.1f}시간" if duration_hours is not None else "-"
    stability_score = current.get("stability_score")
    stability_text = f"{float(stability_score):.2f}" if stability_score is not None else "-"
    summary_line = "-"
    if current.get("current_state") and duration_hours is not None:
        summary_line = (
            f"현재 {current.get('current_state')} 상태가 "
            f"{float(duration_hours):.1f}시간 이어지고 있습니다."
        )
    return {
        "enabled": bool(payload and current),
        "title": str(payload.get("title") or "상태 전이 요약").strip(),
        "description": str(payload.get("description") or "").strip(),
        "summary_line": summary_line,
        "cards": [
            {"label": "현재 상태", "value": current.get("current_state") or "-"},
            {"label": "지속 시간", "value": duration_text},
            {"label": "최근 5일 전이", "value": f"{current.get('transition_count_5d', 0)}회"},
            {"label": "안정성 점수", "value": stability_text},
        ],
        "recent_changes": recent_changes,
    }


def _build_market_model_background_view(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(payload),
        "title": str(payload.get("title") or "모델 해석 백그라운드").strip(),
        "description": str(payload.get("description") or "").strip(),
        "briefing_tone": str(payload.get("briefing_tone") or "-").strip(),
        "summary_line": str(payload.get("summary_line") or "-").strip(),
        "reference_note": str(payload.get("reference_note") or "-").strip(),
        "points": [
            str(item).strip()
            for item in (payload.get("model_background_points") or [])
            if str(item).strip()
        ],
        "favorable_signals": [
            str(item).strip()
            for item in (payload.get("favorable_signals") or [])
            if str(item).strip()
        ],
        "caution_signals": [
            str(item).strip()
            for item in (payload.get("caution_signals") or [])
            if str(item).strip()
        ],
    }


def _build_market_home_extra_view(
    asset_strength_payload: dict[str, Any], state_transition_payload: dict[str, Any]
) -> dict[str, Any]:
    top_assets = [
        str(item.get("asset_group") or "-")
        for item in (asset_strength_payload.get("top_assets") or [])[:2]
    ]
    if top_assets:
        return {
            "enabled": True,
            "label": "현재 상대적으로 강한 자산",
            "value": ", ".join(top_assets),
            "description": "시장 브리핑의 자산군 상대강도 기준입니다.",
        }
    current = state_transition_payload.get("current") or {}
    duration_hours = current.get("duration_hours")
    if current.get("current_state") and duration_hours is not None:
        return {
            "enabled": True,
            "label": "현재 상태 지속시간",
            "value": f"{current.get('current_state')} {float(duration_hours):.1f}시간",
            "description": "상태 전이 요약 기준으로 현재 시장상태 지속시간을 보여 줍니다.",
        }
    return {"enabled": False}


def _build_market_today_background_view(model_background_payload: dict[str, Any]) -> dict[str, Any]:
    points = [
        str(item).strip()
        for item in (model_background_payload.get("model_background_points") or [])[:2]
        if str(item).strip()
    ]
    return {
        "enabled": bool(
            model_background_payload and (points or model_background_payload.get("briefing_tone"))
        ),
        "title": "이번 해석 배경",
        "briefing_tone": str(model_background_payload.get("briefing_tone") or "-").strip(),
        "points": points,
    }


def _coerce_change_pct(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_market_next_day_asset_view(asset: dict[str, Any]) -> dict[str, Any]:
    code = str(asset.get("asset_code") or "").strip()
    change_pct = _coerce_change_pct(asset.get("change_pct"))
    if change_pct is None:
        change_display = "-"
        direction_label = "보합"
        tone = "neutral"
    else:
        change_display = f"{change_pct * 100:+.2f}%"
        if abs(change_pct) < 0.0005:
            direction_label = "보합"
            tone = "neutral"
        elif change_pct > 0:
            direction_label = "상승"
            tone = "good"
        else:
            direction_label = "하락"
            tone = "caution"
    return {
        "asset_code": code,
        "asset_name": NEXT_DAY_PREVIEW_ASSET_LABELS.get(
            code,
            str(asset.get("asset_name") or code or "야간 자산").strip() or "야간 자산",
        ),
        "change_display": change_display,
        "direction_label": direction_label,
        "tone": tone,
        "is_fallback": bool(asset.get("is_fallback")),
    }


def _is_publishable_next_day_asset(asset: dict[str, Any]) -> bool:
    if bool(asset.get("is_fallback")):
        return False
    return _coerce_change_pct(asset.get("change_pct")) is not None


def _build_market_next_day_assets_view(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_assets = [asset for asset in assets if isinstance(asset, dict)]
    asset_by_code = {}
    for asset in normalized_assets:
        code = str(asset.get("asset_code") or "").strip()
        if code and code not in asset_by_code:
            asset_by_code[code] = asset

    selected: list[dict[str, Any]] = []
    used_codes: set[str] = set()

    for code in ("KOSPI200_NIGHT_FUT", "KOREA_PROXY_EWY", "SP500_FUT", "USDKRW"):
        asset = asset_by_code.get(code)
        if asset is None or code in used_codes or not _is_publishable_next_day_asset(asset):
            continue
        selected.append(_build_market_next_day_asset_view(asset))
        used_codes.add(code)
        if len(selected) >= 3:
            break

    for asset in normalized_assets:
        code = str(asset.get("asset_code") or "").strip()
        if not code or code in used_codes:
            continue
        if not _is_publishable_next_day_asset(asset):
            continue
        selected.append(_build_market_next_day_asset_view(asset))
        used_codes.add(code)
        if len(selected) >= 3:
            break

    return selected[:3]


def _build_market_next_day_preview_view(payload: dict[str, Any]) -> dict[str, Any]:
    preview_payload = payload or {}
    active_now = preview_payload.get("active_now") is True
    supporting_points = [
        str(item).strip()
        for item in (preview_payload.get("supporting_points") or [])
        if str(item).strip()
    ][:2]
    risk_points = [
        str(item).strip()
        for item in (preview_payload.get("risk_points") or [])
        if str(item).strip()
    ][:2]
    preview_label = str(preview_payload.get("preview_label") or "").strip()
    headline_line = str(preview_payload.get("headline_line") or "").strip()
    summary_line = str(preview_payload.get("summary_line") or "").strip()
    short_notice = str(
        (preview_payload.get("notice_block") or {}).get("short_notice")
        or DEFAULT_NEXT_DAY_PREVIEW_NOTICE
    ).strip()
    key_assets = _build_market_next_day_assets_view(preview_payload.get("overnight_assets") or [])
    biases = (
        preview_payload.get("biases") if isinstance(preview_payload.get("biases"), dict) else {}
    )
    key_asset_codes = {asset.get("asset_code") for asset in key_assets}
    korea_signal_note = ""
    if (
        biases.get("korea_signal_alignment") == "mixed"
        and "KOSPI200_NIGHT_FUT" in key_asset_codes
        and "KOREA_PROXY_EWY" in key_asset_codes
    ):
        korea_signal_note = "국내/해외 한국 신호가 엇갈려 장초반 변동성 확인이 필요합니다."
    compact_assets = key_assets[:2]
    compact_asset_line = ", ".join(
        f"{item['asset_name']} {item['change_display']}"
        for item in compact_assets
        if item.get("change_display")
    )
    home_line = preview_label or headline_line or summary_line
    today_line = summary_line or headline_line or preview_label
    weekly_point = (
        supporting_points[0]
        if supporting_points
        else (summary_line or headline_line or preview_label)
    )
    display_title = str(preview_payload.get("display_title") or "내일 시장 전망").strip()
    if display_title == "내일 시장 전망 참고":
        display_title = "내일 시장 전망"
    return {
        "enabled": bool(preview_payload),
        "show_default": bool(preview_payload) and active_now,
        "show_market_analysis": bool(preview_payload),
        "active_now": active_now,
        "title": "내일 시장 전망",
        "display_title": display_title,
        "display_subtitle": str(preview_payload.get("display_subtitle") or "").strip(),
        "preview_label": preview_label,
        "preview_score": preview_payload.get("preview_score"),
        "headline_line": headline_line,
        "summary_line": summary_line,
        "supporting_points": supporting_points,
        "risk_points": risk_points,
        "short_notice": short_notice,
        "active_window": str(preview_payload.get("active_window") or "").strip(),
        "reference_session": str(preview_payload.get("reference_session") or "").strip(),
        "market_flow_label": str(preview_payload.get("market_flow_label") or "").strip(),
        "market_flow_reference_note": str(
            preview_payload.get("market_flow_reference_note") or ""
        ).strip(),
        "material_change_flag": preview_payload.get("material_change_flag") is True,
        "is_muted": (preview_payload.get("material_change_flag") is False) or (not active_now),
        "content_hash": str(preview_payload.get("content_hash") or "").strip(),
        "home_line": home_line,
        "today_line": today_line,
        "weekly_point": weekly_point,
        "key_assets": key_assets,
        "korea_signal_note": korea_signal_note,
        "compact_assets": compact_assets,
        "compact_asset_line": compact_asset_line,
    }


def _unwrap_market_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _build_market_analysis_tabs_view(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    source = _unwrap_market_payload(payload)
    source_tabs = source.get("tabs") if isinstance(source.get("tabs"), list) else []
    tabs_by_key = {
        str(tab.get("key") or tab.get("id") or "").strip(): tab
        for tab in source_tabs
        if isinstance(tab, dict)
    }
    tabs = []
    for default_tab in MARKET_ANALYSIS_DATA_TABS:
        source_tab = tabs_by_key.get(default_tab["key"]) or {}
        tabs.append(
            {
                "key": default_tab["key"],
                "label": str(source_tab.get("label") or default_tab["label"]).strip(),
                "description": str(
                    source_tab.get("description") or default_tab["description"]
                ).strip(),
            }
        )
    return tabs


def _market_component_label(key: str) -> str:
    labels = {
        "trend_score": "추세",
        "breadth_score": "시장 폭",
        "risk_score": "위험/변동성",
        "defensive_flow_score": "방어 흐름",
    }
    return labels.get(key, key)


def _build_market_component_chart_views(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    components = []
    for key in ("trend_score", "breadth_score", "risk_score", "defensive_flow_score"):
        series = []
        for point in points[-120:]:
            value = _safe_float(point.get(key))
            if value is None:
                continue
            series.append(
                {
                    "label": _format_kst_datetime(point.get("asof")),
                    "score": value,
                }
            )
        latest_value = series[-1]["score"] if series else None
        components.append(
            {
                "key": key,
                "label": _market_component_label(key),
                "latest_display": f"{latest_value:.2f}" if latest_value is not None else "-",
                "series": series,
                "enabled": len(series) >= 2,
            }
        )
    return components


def _build_market_asset_rank_change_view(payload: dict[str, Any]) -> list[dict[str, Any]]:
    series = [row for row in (payload.get("series") or []) if isinstance(row, dict)]
    asof_values = sorted({str(row.get("asof") or "") for row in series if row.get("asof")})
    if len(asof_values) < 2:
        return []
    previous_asof, latest_asof = asof_values[-2], asof_values[-1]
    previous = {
        str(row.get("asset_group") or ""): _safe_float(row.get("strength_rank"))
        for row in series
        if str(row.get("asof") or "") == previous_asof
    }
    latest_rows = [
        row
        for row in series
        if str(row.get("asof") or "") == latest_asof and row.get("asset_group")
    ]
    changes = []
    for row in sorted(latest_rows, key=lambda item: _safe_float(item.get("strength_rank")) or 999):
        asset_group = str(row.get("asset_group") or "-")
        latest_rank = _safe_float(row.get("strength_rank"))
        previous_rank = previous.get(asset_group)
        rank_delta = None
        if latest_rank is not None and previous_rank is not None:
            rank_delta = int(previous_rank - latest_rank)
        if rank_delta is None:
            delta_display = "-"
        elif rank_delta > 0:
            delta_display = f"{rank_delta}계단 상승"
        elif rank_delta < 0:
            delta_display = f"{abs(rank_delta)}계단 하락"
        else:
            delta_display = "변화 없음"
        changes.append(
            {
                "asset_group": asset_group,
                "latest_rank": int(latest_rank) if latest_rank is not None else "-",
                "previous_rank": int(previous_rank) if previous_rank is not None else "-",
                "delta_display": delta_display,
            }
        )
    return changes[:8]


def _build_market_live_context_view(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = _unwrap_market_payload(payload)
    cards = []
    candidate_rows = []
    for key in ("cards", "items", "sections", "signals", "contexts"):
        value = source.get(key)
        if isinstance(value, list):
            candidate_rows.extend([row for row in value if isinstance(row, dict)])
    if not candidate_rows and source:
        for key, value in source.items():
            if isinstance(value, dict):
                candidate_rows.append({"title": key, **value})
    for row in candidate_rows[:6]:
        title = str(row.get("title") or row.get("label") or row.get("name") or "참고 항목").strip()
        value = str(
            row.get("display_value")
            or row.get("value")
            or row.get("state_label")
            or row.get("summary")
            or row.get("description")
            or "-"
        ).strip()
        description = str(
            row.get("description") or row.get("summary_line") or row.get("reference_note") or ""
        ).strip()
        cards.append({"title": title, "value": value, "description": description})
    return {
        "enabled": bool(source),
        "title": str(
            source.get("display_title") or source.get("title") or "장중/야간 참고"
        ).strip(),
        "summary_line": str(
            source.get("summary_line")
            or source.get("headline_line")
            or "장중 참고 데이터와 종가 기준 데이터를 분리해 보여줍니다."
        ).strip(),
        "cards": cards,
    }


def _build_market_data_guide_view(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = _unwrap_market_payload(payload)
    raw_sections = []
    for key in ("sections", "guide_sections", "items", "data_sources"):
        value = source.get(key)
        if isinstance(value, list):
            raw_sections.extend([row for row in value if isinstance(row, dict)])
    if not raw_sections:
        raw_sections = [
            {
                "title": "official",
                "description": "공식 데이터 또는 공식 산출값입니다.",
            },
            {
                "title": "official_delayed",
                "description": "공식 데이터이나 공개 지연 가능성이 있는 항목입니다.",
            },
            {
                "title": "proxy",
                "description": "직접 지표가 없을 때 사용하는 대체 참고 지표입니다.",
            },
            {
                "title": "fallback",
                "description": "원천 데이터 지연 시 임시로 사용하는 보조값입니다.",
            },
        ]
    sections = []
    for row in raw_sections[:12]:
        lines = [
            str(item).strip()
            for item in (row.get("lines") or row.get("body") or row.get("bullets") or [])
            if str(item).strip()
        ]
        sections.append(
            {
                "title": str(
                    row.get("title")
                    or row.get("label")
                    or row.get("source_type")
                    or row.get("key")
                    or "데이터 항목"
                ).strip(),
                "description": str(
                    row.get("description")
                    or row.get("summary")
                    or row.get("meaning")
                    or row.get("note")
                    or ""
                ).strip(),
                "lines": lines[:4],
            }
        )
    return {
        "enabled": bool(source or sections),
        "title": str(source.get("display_title") or source.get("title") or "데이터 해설").strip(),
        "summary_line": str(
            source.get("summary_line")
            or source.get("description")
            or "시장 분석에 사용되는 지표의 의미와 데이터 성격을 정리합니다."
        ).strip(),
        "sections": sections,
    }


def _format_count(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


def _dart_type_label(row: dict[str, Any]) -> str:
    return str(
        row.get("label")
        or row.get("type_label")
        or row.get("filing_type")
        or row.get("type")
        or row.get("category")
        or "공시 유형"
    ).strip()


def _dart_type_count(row: dict[str, Any]) -> Any:
    return row.get("count", row.get("filing_count", row.get("value")))


def _dart_filing_title(row: dict[str, Any]) -> str:
    return str(
        row.get("title")
        or row.get("report_nm")
        or row.get("filing_title")
        or row.get("report_name")
        or "공시 제목"
    ).strip()


def _dart_filing_company(row: dict[str, Any]) -> str:
    return str(row.get("corp_name") or row.get("company_name") or row.get("company") or "").strip()


def _dart_filing_date(row: dict[str, Any]) -> str:
    return str(
        row.get("filing_date")
        or row.get("receipt_date")
        or row.get("rcept_dt")
        or row.get("date")
        or ""
    ).strip()


def _dart_filing_url(row: dict[str, Any]) -> str:
    return str(row.get("url") or row.get("filing_url") or row.get("dart_url") or "").strip()


def _build_market_dart_summary_view(
    current_payload: dict[str, Any] | None,
    history_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    current = _unwrap_market_payload(current_payload)
    history = _unwrap_market_payload(history_payload)
    enabled = current.get("enabled", True) is not False and bool(current)
    market_breakdown = current.get("market_breakdown") or {}
    filing_types = []
    for row in current.get("filing_count_by_type") or []:
        if not isinstance(row, dict):
            continue
        filing_types.append(
            {
                "label": _dart_type_label(row),
                "count_display": _format_count(_dart_type_count(row)),
            }
        )
    highlights = []
    for row in (current.get("highlights") or [])[:5]:
        if not isinstance(row, dict):
            continue
        highlights.append(
            {
                "title": _dart_filing_title(row),
                "company": _dart_filing_company(row),
                "date": _dart_filing_date(row),
                "date_display": _format_market_kst_label(_dart_filing_date(row)),
                "url": _dart_filing_url(row),
            }
        )
    recent_filings = []
    for row in (current.get("recent_filings") or [])[:8]:
        if not isinstance(row, dict):
            continue
        recent_filings.append(
            {
                "title": _dart_filing_title(row),
                "company": _dart_filing_company(row),
                "date": _dart_filing_date(row),
                "date_display": _format_market_kst_label(_dart_filing_date(row)),
                "url": _dart_filing_url(row),
            }
        )

    series_rows = [row for row in (history.get("series") or []) if isinstance(row, dict)]
    total_series = []
    risk_series = []
    for row in series_rows[-120:]:
        label = str(row.get("reference_date") or row.get("asof") or "").strip()
        total_value = _safe_float(row.get("filing_count_total"))
        risk_value = _safe_float(row.get("risk_event_count"))
        if label and total_value is not None:
            total_series.append(
                {
                    "label": _format_chart_date_label(label),
                    "score": total_value,
                    "value_label": _format_count(total_value),
                }
            )
        if label and risk_value is not None:
            risk_series.append(
                {
                    "label": _format_chart_date_label(label),
                    "score": risk_value,
                    "value_label": _format_count(risk_value),
                }
            )

    return {
        "enabled": enabled,
        "show_fallback": bool(current) and not enabled,
        "reference_date": _format_market_kst_label(
            current.get("reference_date") or current.get("asof")
        ),
        "summary_line": ("상장사 공시 흐름을 OpenDART 기준으로 정리한 공개형 참고 정보입니다."),
        "disclaimer": (
            "공시 건수는 시장 상황 이해를 돕는 참고 지표이며, 특정 종목의 매수·매도 "
            "판단을 직접 제시하지 않습니다."
        ),
        "metrics": [
            {"label": "전체 공시", "value": _format_count(current.get("filing_count_total"))},
            {"label": "코스피", "value": _format_count(market_breakdown.get("kospi_count"))},
            {"label": "코스닥", "value": _format_count(market_breakdown.get("kosdaq_count"))},
            {"label": "리스크 공시", "value": _format_count(current.get("risk_event_count"))},
        ],
        "filing_types": filing_types,
        "highlights": highlights,
        "recent_filings": recent_filings,
        "total_series": total_series,
        "risk_series": risk_series,
        "history_enabled": bool(total_series or risk_series),
    }


def _series_chart(
    rows: list[dict[str, Any]],
    *,
    key: str,
    label_key: str = "asof",
    limit: int = 120,
    percent: bool = False,
) -> list[dict[str, Any]]:
    series = []
    for row in rows[-limit:]:
        value = _safe_float(row.get(key))
        label = str(row.get(label_key) or row.get("asof") or "").strip()
        if value is None or not label:
            continue
        series.append(
            {
                "label": _format_chart_date_label(label),
                "score": value,
                "value_label": _format_percent(value) if percent else f"{value:.2f}",
            }
        )
    return series


def _latest_value_display(rows: list[dict[str, Any]], key: str, *, percent: bool = False) -> str:
    for row in reversed(rows):
        value = _safe_float(row.get(key))
        if value is None:
            continue
        return _format_percent(value) if percent else f"{value:.2f}"
    return "-"


def _build_market_breadth_detail_view(
    current_payload: dict[str, Any] | None,
    history_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    current = _unwrap_market_payload(current_payload)
    history = _unwrap_market_payload(history_payload)
    close_series = [
        row
        for row in (history.get("close_series") or history.get("series") or [])
        if isinstance(row, dict)
    ]
    intraday_series = [
        row for row in (history.get("intraday_series") or []) if isinstance(row, dict)
    ]
    close_charts = [
        {
            "key": "above_20dma_ratio",
            "title": "20일선 위 종목 비율",
            "unit": "비율",
            "latest": _latest_value_display(close_series, "above_20dma_ratio", percent=True),
            "series": _series_chart(close_series, key="above_20dma_ratio", percent=True),
        },
        {
            "key": "above_60dma_ratio",
            "title": "60일선 위 종목 비율",
            "unit": "비율",
            "latest": _latest_value_display(close_series, "above_60dma_ratio", percent=True),
            "series": _series_chart(close_series, key="above_60dma_ratio", percent=True),
        },
        {
            "key": "adv_dec_ratio",
            "title": "상승/하락 종목 비율",
            "unit": "배율",
            "latest": _latest_value_display(close_series, "adv_dec_ratio"),
            "series": _series_chart(close_series, key="adv_dec_ratio"),
        },
    ]
    intraday_charts = []
    for universe_code in ("KOSPI", "KOSDAQ"):
        rows = [
            row
            for row in intraday_series
            if str(row.get("universe_code") or "").upper() == universe_code
        ]
        intraday_charts.append(
            {
                "key": universe_code.lower(),
                "title": f"{universe_code} 장중 상승 종목 비율",
                "latest": _latest_value_display(rows, "positive_ratio", percent=True),
                "series": _series_chart(rows, key="positive_ratio", percent=True),
            }
        )
    latest_close = close_series[-1] if close_series else {}
    latest_intraday = intraday_series[-1] if intraday_series else {}
    return {
        "enabled": bool(current or close_series or intraday_series),
        "summary_line": (
            "이 차트는 시장 안쪽 종목들의 확산 흐름을 보여주는 공개형 참고 정보입니다."
        ),
        "latest_close_asof": _format_market_kst_label(
            (history.get("summary") or {}).get("latest_close_asof")
            or latest_close.get("asof")
            or current.get("latest_close_asof")
        ),
        "latest_intraday_asof": _format_market_kst_label(
            (history.get("summary") or {}).get("latest_intraday_asof")
            or latest_intraday.get("asof")
            or current.get("latest_intraday_asof")
        ).strip(),
        "close_metrics": [
            {
                "label": "20일선 위",
                "value": _latest_value_display(close_series, "above_20dma_ratio", percent=True),
            },
            {
                "label": "60일선 위",
                "value": _latest_value_display(close_series, "above_60dma_ratio", percent=True),
            },
            {
                "label": "상승/하락 비율",
                "value": _latest_value_display(close_series, "adv_dec_ratio"),
            },
            {
                "label": "신고가/신저가",
                "value": (
                    f"{_format_count(latest_close.get('new_high_count'))} / "
                    f"{_format_count(latest_close.get('new_low_count'))}"
                    if latest_close
                    else "-"
                ),
            },
        ],
        "close_charts": close_charts,
        "intraday_charts": intraday_charts,
    }


US_MACRO_ASSET_LABELS = {
    "KOREA_PROXY_EWY": "한국 관련 야간 프록시(EWY)",
    "SP500_FUT": "S&P500 선물",
    "NASDAQ100_FUT": "나스닥100 선물",
    "USDKRW": "USD/KRW",
    "WTI": "WTI",
    "US10Y": "미국 10년 금리",
}


def _build_market_us_macro_panel_view(
    current_payload: dict[str, Any] | None,
    history_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    current = _unwrap_market_payload(current_payload)
    history = _unwrap_market_payload(history_payload)
    asset_series = [
        row
        for row in (history.get("asset_series") or history.get("series") or [])
        if isinstance(row, dict)
    ]
    preview_series = [row for row in (history.get("preview_series") or []) if isinstance(row, dict)]
    asset_charts = []
    for asset_code, asset_label in US_MACRO_ASSET_LABELS.items():
        rows = [
            row for row in asset_series if str(row.get("asset_code") or "").upper() == asset_code
        ]
        asset_charts.append(
            {
                "asset_code": asset_code,
                "title": asset_label,
                "latest": _latest_value_display(rows, "change_pct", percent=True),
                "status_label": (
                    str(rows[-1].get("status_label") or rows[-1].get("direction_label") or "-")
                    if rows
                    else "-"
                ),
                "series": _series_chart(rows, key="change_pct", percent=True),
            }
        )
    preview_charts = [
        {
            "key": "preview_score",
            "title": "preview score",
            "latest": _latest_value_display(preview_series, "preview_score"),
            "series": _series_chart(preview_series, key="preview_score"),
        },
        {
            "key": "overnight_futures_bias",
            "title": "야간 선물 bias",
            "latest": _latest_value_display(preview_series, "overnight_futures_bias"),
            "series": _series_chart(preview_series, key="overnight_futures_bias"),
        },
        {
            "key": "global_risk_bias",
            "title": "글로벌 위험 bias",
            "latest": _latest_value_display(preview_series, "global_risk_bias"),
            "series": _series_chart(preview_series, key="global_risk_bias"),
        },
        {
            "key": "overnight_fx_bias",
            "title": "야간 환율 bias",
            "latest": _latest_value_display(preview_series, "overnight_fx_bias"),
            "series": _series_chart(preview_series, key="overnight_fx_bias"),
        },
    ]
    latest_preview = preview_series[-1] if preview_series else {}
    return {
        "enabled": bool(current or asset_series or preview_series),
        "summary_line": (
            "야간 글로벌 지표는 다음 거래일 장초반 환경을 참고하기 위한 정보이며, "
            "국내 퀀트모델 시장 흐름 자체를 대체하지 않습니다."
        ),
        "latest_asset_asof": _format_market_kst_label(
            (history.get("summary") or {}).get("latest_asset_asof")
            or (asset_series[-1].get("asof") if asset_series else "")
        ),
        "latest_preview_asof": _format_market_kst_label(
            (history.get("summary") or {}).get("latest_preview_asof") or latest_preview.get("asof")
        ),
        "headline_line": str(
            current.get("headline_line")
            or latest_preview.get("headline_line")
            or latest_preview.get("summary_line")
            or ""
        ).strip(),
        "asset_charts": asset_charts,
        "preview_charts": preview_charts,
    }


def _build_market_analysis_data_view(market_bundle: Any) -> dict[str, Any]:
    timeline_payload = (
        market_bundle.timeline_history or market_bundle.timeline if market_bundle else {}
    )
    asset_strength_payload = (
        market_bundle.asset_strength_history or market_bundle.asset_strength
        if market_bundle
        else {}
    )
    timeline_view = _build_market_timeline_view(timeline_payload)
    asset_strength_view = _build_market_asset_strength_view(asset_strength_payload)
    state_transition_view = _build_market_state_transition_view(
        market_bundle.state_transition if market_bundle else {}
    )
    page_view = _build_market_page_view(market_bundle.page if market_bundle else {})
    points = _build_market_timeline_points(timeline_payload)
    return {
        "page_title": "시장 분석",
        "subtitle": (
            "시장 브리핑의 해석 요약과 분리해, current와 history 데이터를 "
            "차트 중심으로 확인합니다."
        ),
        "asof": _format_market_kst_label(market_bundle.asof if market_bundle else None),
        "tabs": _build_market_analysis_tabs_view(
            market_bundle.analysis_tabs if market_bundle else {}
        ),
        "timeline": timeline_view,
        "component_charts": _build_market_component_chart_views(points),
        "state_transition": state_transition_view,
        "asset_strength": asset_strength_view,
        "asset_rank_changes": _build_market_asset_rank_change_view(asset_strength_payload),
        "live_context": _build_market_live_context_view(
            market_bundle.live_context if market_bundle else {}
        ),
        "state_bridge": page_view.get("state_intraday_bridge_view"),
        "state_bar": page_view.get("state_bar"),
        "next_day_preview": _build_market_next_day_preview_view(
            market_bundle.next_day_preview if market_bundle else {}
        ),
        "data_guide": _build_market_data_guide_view(
            market_bundle.data_guide if market_bundle else {}
        ),
        "dart_summary": _build_market_dart_summary_view(
            market_bundle.dart_summary if market_bundle else {},
            market_bundle.dart_summary_history if market_bundle else {},
        ),
        "breadth_detail": _build_market_breadth_detail_view(
            market_bundle.breadth_detail if market_bundle else {},
            market_bundle.breadth_detail_history if market_bundle else {},
        ),
        "us_macro_panel": _build_market_us_macro_panel_view(
            market_bundle.us_macro_panel if market_bundle else {},
            market_bundle.us_macro_panel_history if market_bundle else {},
        ),
    }


MARKET_ENVIRONMENT_SECTION_ORDER = (
    ("domestic_source", "국내 시장 원천 데이터"),
    ("fred_macro", "FRED 매크로/금리 데이터"),
    ("yahoo_global", "Yahoo 글로벌 시장 데이터"),
)


def _format_environment_value(value: Any, unit: Any = "") -> str:
    numeric = _safe_float(value)
    unit_text = str(unit or "").strip()
    if numeric is None:
        return "-"
    if unit_text in {"%", "percent", "pct"}:
        return f"{numeric:.2f}%"
    if abs(numeric) >= 1000:
        return f"{numeric:,.2f}".rstrip("0").rstrip(".")
    if abs(numeric) >= 10:
        return f"{numeric:.2f}".rstrip("0").rstrip(".")
    return f"{numeric:.4f}".rstrip("0").rstrip(".")


def _build_environment_series_chart(
    points: list[dict[str, Any]],
    *,
    unit: Any = "",
    limit: int = 260,
) -> list[dict[str, Any]]:
    series = []
    for point in points[-limit:]:
        if not isinstance(point, dict):
            continue
        value = _safe_float(point.get("value"))
        label = str(point.get("date") or point.get("asof") or "").strip()
        if value is None or not label:
            continue
        series.append(
            {
                "label": _format_chart_date_label(label),
                "score": value,
                "value_label": _format_environment_value(value, unit),
            }
        )
    return series


def _build_market_environment_indicators_view(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = _unwrap_market_payload(payload)
    source_sections = [row for row in (source.get("sections") or []) if isinstance(row, dict)]
    sections_by_key = {
        str(
            row.get("section_key") or row.get("section_id") or row.get("key") or row.get("id") or ""
        ).strip(): row
        for row in source_sections
    }
    chart_policy = (
        source.get("chart_policy") if isinstance(source.get("chart_policy"), dict) else {}
    )
    default_height = int(chart_policy.get("default_chart_height_px") or 160)
    popup_height = int(chart_policy.get("popup_chart_height_px") or 420)
    sections = []
    total_series_count = 0
    for section_key, fallback_title in MARKET_ENVIRONMENT_SECTION_ORDER:
        section = sections_by_key.get(section_key) or {}
        raw_series = [row for row in (section.get("series") or []) if isinstance(row, dict)]
        series_cards = []
        for row in raw_series:
            points = [point for point in (row.get("points") or []) if isinstance(point, dict)]
            unit = row.get("unit") or ""
            chart_series = _build_environment_series_chart(points, unit=unit)
            latest_value = row.get("latest_value")
            series_cards.append(
                {
                    "series_id": str(row.get("series_id") or "").strip(),
                    "title": str(
                        row.get("display_name_kr") or row.get("series_id") or "지표"
                    ).strip(),
                    "category": str(row.get("category_label_kr") or "").strip(),
                    "source_provider": str(row.get("source_provider") or "-").strip(),
                    "source_detail": str(row.get("source_detail") or "-").strip(),
                    "source_tier": str(row.get("source_tier") or "").strip(),
                    "unit": str(unit).strip(),
                    "frequency": str(row.get("frequency") or "-").strip(),
                    "period_label": str(row.get("period_label") or "").strip(),
                    "latest_date": _format_market_kst_label(row.get("latest_date")),
                    "latest_value": _format_environment_value(latest_value, unit),
                    "row_count": _format_count(row.get("row_count")),
                    "chart_height": int(row.get("default_chart_height_px") or default_height),
                    "popup_enabled": row.get("popup_enabled", True) is not False,
                    "chart_series": chart_series,
                    "has_data": bool(chart_series),
                }
            )
        total_series_count += len(series_cards)
        sections.append(
            {
                "key": section_key,
                "title": str(
                    section.get("display_title") or section.get("title") or fallback_title
                ).strip(),
                "description": str(section.get("description") or "").strip(),
                "coverage_warning": str(section.get("coverage_warning") or "").strip(),
                "series": series_cards,
            }
        )
    notice_block = (
        source.get("notice_block") if isinstance(source.get("notice_block"), dict) else {}
    )
    return {
        "enabled": bool(source),
        "page_title": str(source.get("title") or "시장 환경 지표").strip(),
        "description": str(
            source.get("description")
            or (
                "국내 지수와 환율, 미국 금리와 물가, 글로벌 ETF 흐름을 한 화면에서 "
                "확인하는 공개형 시장 데이터입니다."
            )
        ).strip(),
        "asof": _format_market_kst_label(source.get("asof")),
        "generated_at": _format_market_kst_label(source.get("generated_at")),
        "timezone": str(source.get("timezone") or "Asia/Seoul").strip(),
        "sections": sections,
        "total_series_count": total_series_count,
        "popup_chart_height": popup_height,
        "notice_title": str(notice_block.get("title") or "주의사항").strip(),
        "notice_body": [
            str(item).strip() for item in (notice_block.get("body") or []) if str(item).strip()
        ]
        or [
            (
                "본 정보는 공개 시장 데이터의 흐름을 보여주는 참고 자료이며, "
                "특정 종목이나 자산의 매수·매도 권유가 아닙니다."
            )
        ],
        "data_note": (
            "차트는 화면 성능을 위해 최근 3년 구간을 우선 표시하며, "
            "각 지표의 전체 보유기간은 기간 정보로 함께 제공합니다."
        ),
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
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
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


def _preview_date_context_rows(date_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    date_context = date_context or {}
    label_map = {
        "asof_date": "기준일",
        "signal_date": "신호일",
        "effective_date": "반영일",
        "week_end": "주간 종료일",
        "asset_mix_week_end": "자산구조 주차",
        "quality_week_end": "품질 기준 주차",
    }
    rows: list[dict[str, Any]] = []
    for key in (
        "asof_date",
        "signal_date",
        "effective_date",
        "week_end",
        "asset_mix_week_end",
        "quality_week_end",
    ):
        value = date_context.get(key)
        if value:
            rows.append({"label": label_map.get(key, key), "value": value})
    return rows


def _preview_quality_checks_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    label_map = {
        "asset_mix_gross_weight": "자산구조 합계",
        "change_log_below_threshold": "변화 threshold",
        "change_log_null_name": "변화 종목명 누락",
        "lifecycle_reentries": "재진입 분리",
        "quality_current_drawdown": "현재 drawdown",
    }
    normalized: list[dict[str, Any]] = []
    for row in rows or []:
        normalized.append(
            {
                "label": label_map.get(
                    str(row.get("check_name") or ""), row.get("check_name") or "-"
                ),
                "status": row.get("status") or "-",
                "metric_value": row.get("metric_value"),
                "detail": row.get("detail") or "-",
            }
        )
    return normalized


def _preview_file_meta_rows(file_meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, meta in (file_meta or {}).items():
        rows.append(
            {
                "key": key,
                "path": meta.get("path") or "-",
                "exists": bool(meta.get("exists")),
                "size_bytes": meta.get("size_bytes"),
                "md5": meta.get("md5") or "-",
            }
        )
    return rows


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
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
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
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
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


def _preview_change_log_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows or []:
        change_type = str(row.get("change_type") or "").lower()
        normalized.append(
            {
                "week_end": row.get("week_end") or "-",
                "ticker": row.get("ticker") or "-",
                "name": row.get("name") or "종목명 미표시",
                "change_type": change_type,
                "change_label": PREVIEW_CHANGE_TYPE_LABELS.get(change_type, change_type or "변화"),
                "delta_weight": row.get("delta_weight"),
            }
        )
    return normalized


def _build_preview_performance_interpretation_view(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    interpretation = payload or {}
    if not interpretation:
        return None

    top_contributors = []
    for row in interpretation.get("top_contributors_12w") or []:
        contribution = row.get("estimated_contribution_12w")
        if contribution is None:
            continue
        top_contributors.append(
            {
                "ticker": str(row.get("ticker") or "-").strip() or "-",
                "name": str(row.get("name") or "-").strip() or "-",
                "estimated_contribution_12w": contribution,
            }
        )

    summary_cards = [
        {"label": "성과 구간", "value": interpretation.get("window_weeks"), "kind": "weeks"},
        {
            "label": "최근 12주 누적수익률",
            "value": interpretation.get("cumulative_return_12w"),
            "kind": "percent",
        },
        {
            "label": "연환산 변동성",
            "value": interpretation.get("annualized_volatility_12w"),
            "kind": "percent",
        },
    ]

    detail_rows = [
        {
            "label": "구간 시작",
            "value": str(interpretation.get("window_start_week_end") or "-").strip() or "-",
            "kind": "text",
        },
        {
            "label": "구간 종료",
            "value": str(interpretation.get("window_end_week_end") or "-").strip() or "-",
            "kind": "text",
        },
        {
            "label": "최고 주간 수익률",
            "value": interpretation.get("best_weekly_return_12w"),
            "kind": "percent",
            "suffix": str(interpretation.get("best_weekly_return_week_end") or "-").strip() or "-",
        },
        {
            "label": "최저 주간 수익률",
            "value": interpretation.get("worst_weekly_return_12w"),
            "kind": "percent",
            "suffix": str(interpretation.get("worst_weekly_return_week_end") or "-").strip() or "-",
        },
        {
            "label": "상승 주 수",
            "value": interpretation.get("positive_weeks_12w", 0),
            "kind": "count",
        },
        {
            "label": "하락 주 수",
            "value": interpretation.get("negative_weeks_12w", 0),
            "kind": "count",
        },
        {"label": "보합 주 수", "value": interpretation.get("flat_weeks_12w", 0), "kind": "count"},
    ]

    return {
        "summary_cards": summary_cards,
        "detail_rows": detail_rows,
        "top_contributors": top_contributors[:5],
    }


def _build_preview_model_quality_view(model: dict[str, Any]) -> dict[str, Any]:
    latest_quality = model.get("latest_quality") or {}
    change_density = model.get("change_density") or {}
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
        "quality_cards": [
            {"label": "CAGR", "value": latest_quality.get("cagr"), "kind": "percent"},
            {"label": "MDD", "value": latest_quality.get("mdd"), "kind": "percent"},
            {"label": "Sharpe", "value": latest_quality.get("sharpe"), "kind": "number"},
            {"label": "최근 4W", "value": latest_quality.get("return_4w"), "kind": "percent"},
            {"label": "최근 12W", "value": latest_quality.get("return_12w"), "kind": "percent"},
            {
                "label": "현재 DD",
                "value": latest_quality.get("current_drawdown"),
                "kind": "percent",
            },
        ],
        "trend_rows": list(model.get("quality_trend_26w") or [])[-26:],
        "change_density_cards": [
            {"label": "신규 8주", "value": change_density.get("new_8w", 0)},
            {"label": "제외 8주", "value": change_density.get("exit_8w", 0)},
            {"label": "비중 확대", "value": change_density.get("increase_8w", 0)},
            {"label": "비중 축소", "value": change_density.get("decrease_8w", 0)},
        ],
        "support_rows": [
            {
                "label": "상대강도 4W",
                "value": latest_quality.get("relative_strength_vs_benchmark_4w"),
                "kind": "percent",
            },
            {
                "label": "상대강도 12W",
                "value": latest_quality.get("relative_strength_vs_benchmark_12w"),
                "kind": "percent",
            },
            {
                "label": "상대강도 52W",
                "value": latest_quality.get("relative_strength_vs_benchmark_52w"),
                "kind": "percent",
            },
            {
                "label": "평균 현금성 4W",
                "value": latest_quality.get("cash_weight_avg_4w"),
                "kind": "percent",
            },
            {
                "label": "평균 보유 수 4W",
                "value": latest_quality.get("holdings_count_avg_4w", 0),
                "kind": "count",
            },
            {
                "label": "주간 turnover",
                "value": latest_quality.get("turnover_1w"),
                "kind": "percent",
            },
            {
                "label": "평균 turnover 4W",
                "value": latest_quality.get("turnover_avg_4w"),
                "kind": "percent",
            },
            {
                "label": "Top 1 비중",
                "value": latest_quality.get("top1_weight"),
                "kind": "percent",
            },
            {
                "label": "Top 3 비중",
                "value": latest_quality.get("top3_weight"),
                "kind": "percent",
            },
            {
                "label": "Top 5 비중",
                "value": latest_quality.get("top5_weight"),
                "kind": "percent",
            },
            {
                "label": "HHI",
                "value": latest_quality.get("holdings_hhi"),
                "kind": "number",
            },
        ],
        "quality_checks": _preview_quality_checks_rows(model.get("quality_checks") or []),
        "performance_interpretation": _build_preview_performance_interpretation_view(
            model.get("performance_interpretation")
        ),
    }


def _build_preview_weekly_briefing_view(model: dict[str, Any]) -> dict[str, Any]:
    summary = model.get("summary") or {}
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
        "summary_cards": [
            {"label": "최근 4W", "value": summary.get("return_4w"), "kind": "percent"},
            {"label": "최근 12W", "value": summary.get("return_12w"), "kind": "percent"},
            {"label": "현재 DD", "value": summary.get("current_drawdown"), "kind": "percent"},
            {"label": "현금 비중", "value": summary.get("cash_weight"), "kind": "percent"},
            {"label": "신규 8W", "value": summary.get("new_8w", 0), "kind": "count"},
            {"label": "제외 8W", "value": summary.get("exit_8w", 0), "kind": "count"},
            {
                "label": "상대강도 12W",
                "value": summary.get("relative_strength_vs_benchmark_12w"),
                "kind": "percent",
            },
            {
                "label": "평균 turnover 4W",
                "value": summary.get("turnover_avg_4w"),
                "kind": "percent",
            },
            {"label": "Top 5 비중", "value": summary.get("top5_weight"), "kind": "percent"},
        ],
        "briefing_points": [
            str(point).strip()
            for point in (model.get("briefing_points") or [])
            if str(point).strip()
        ],
        "top_holdings": _preview_breakdown_rows(model.get("top_holdings") or [])[:5],
        "one_week_changes": _preview_change_log_rows(model.get("one_week_changes") or [])[:12],
        "recent_changes": _preview_change_log_rows(model.get("recent_changes_8w") or [])[:16],
        "performance_interpretation": _build_preview_performance_interpretation_view(
            model.get("performance_interpretation")
        ),
    }


def _preview_asset_detail_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tone_map = {
        "stock_equity": "stock",
        "etf_equity": "etf",
        "etf_bond": "bond",
        "etf_fx": "fx",
        "etf_gold": "gold",
        "etf_inverse": "inverse",
        "etf_covered_call": "income",
        "cash": "cash",
        "etf_other": "other",
        "other": "other",
    }
    label_map = {
        "stock_equity": "주식",
        "etf_equity": "주식 ETF",
        "etf_bond": "채권 ETF",
        "etf_fx": "환율 ETF",
        "etf_gold": "금 ETF",
        "etf_inverse": "인버스 ETF",
        "etf_covered_call": "커버드콜 ETF",
        "cash": "현금성",
        "etf_other": "기타 ETF",
        "other": "기타",
    }
    normalized = []
    for row in rows or []:
        bucket = str(row.get("detail_bucket") or row.get("bucket") or "other")
        normalized.append(
            {
                "bucket": bucket,
                "label": label_map.get(bucket, bucket),
                "value": row.get("bucket_weight"),
                "tone": tone_map.get(bucket, "other"),
            }
        )
    return normalized


def _build_preview_asset_exposure_detail_view(model: dict[str, Any]) -> dict[str, Any]:
    latest_change_activity = model.get("latest_change_activity") or {}
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
        "asset_segments": _preview_asset_detail_segments(model.get("latest_asset_detail") or []),
        "detail_rows": _preview_asset_detail_segments(model.get("latest_asset_detail") or []),
        "trend_rows": [
            {
                "week_end": row.get("week_end") or "-",
                "segments": _preview_asset_detail_segments(
                    [
                        {"detail_bucket": key, "bucket_weight": value}
                        for key, value in (row.get("bucket_weights") or {}).items()
                    ]
                ),
            }
            for row in (model.get("asset_detail_trend_26w") or [])[-26:]
        ],
        "change_cards": [
            {
                "label": "강도 점수",
                "value": latest_change_activity.get("change_intensity_score"),
                "kind": "number",
            },
            {
                "label": "강도 라벨",
                "value": latest_change_activity.get("change_intensity_label") or "-",
                "kind": "text",
            },
            {
                "label": "이벤트 수",
                "value": latest_change_activity.get("event_count_total", 0),
                "kind": "count",
            },
            {
                "label": "절대 변화합",
                "value": latest_change_activity.get("abs_delta_sum"),
                "kind": "percent",
            },
        ],
    }


def _preview_change_impact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows or []:
        normalized.append(
            {
                "event_week_end": row.get("event_week_end") or row.get("week_end") or "-",
                "ticker": row.get("ticker") or "-",
                "name": row.get("name") or "종목명 미표시",
                "delta_weight": row.get("delta_weight"),
                "holding_days_observed": row.get("holding_days_observed"),
                "return_since_entry_observed": row.get("return_since_entry_observed"),
                "outcome_status": row.get("outcome_status") or "-",
            }
        )
    return normalized


def _build_preview_change_impact_view(model: dict[str, Any]) -> dict[str, Any]:
    latest_change_activity = model.get("latest_change_activity") or {}
    impact_summary = model.get("impact_summary") or {}
    return {
        "model_code": model.get("model_code") or "-",
        "display_name": _preview_model_title(model),
        "date_context_rows": _preview_date_context_rows(model.get("date_context")),
        "summary_cards": [
            {
                "label": "신규 수",
                "value": latest_change_activity.get("new_count", 0),
                "kind": "count",
            },
            {
                "label": "제외 수",
                "value": latest_change_activity.get("exit_count", 0),
                "kind": "count",
            },
            {
                "label": "강도 점수",
                "value": latest_change_activity.get("change_intensity_score"),
                "kind": "number",
            },
            {
                "label": "강도 라벨",
                "value": latest_change_activity.get("change_intensity_label") or "-",
                "kind": "text",
            },
            {
                "label": "비중 확대",
                "value": latest_change_activity.get("increase_count", 0),
                "kind": "count",
            },
            {
                "label": "비중 축소",
                "value": latest_change_activity.get("decrease_count", 0),
                "kind": "count",
            },
        ],
        "impact_cards": [
            {
                "label": "신규 이벤트 8W",
                "value": impact_summary.get("new_events_8w", 0),
                "kind": "count",
            },
            {
                "label": "제외 이벤트 8W",
                "value": impact_summary.get("exit_events_8w", 0),
                "kind": "count",
            },
            {
                "label": "신규 관찰수익 평균",
                "value": impact_summary.get("avg_new_return_observed_8w"),
                "kind": "percent",
            },
            {
                "label": "제외 관찰수익 평균",
                "value": impact_summary.get("avg_exit_return_observed_8w"),
                "kind": "percent",
            },
        ],
        "trend_rows": list(model.get("change_activity_trend_26w") or [])[-26:],
        "new_entries": _preview_change_impact_rows(model.get("recent_new_entries_impact_8w") or []),
        "exits": _preview_change_impact_rows(model.get("recent_exits_impact_8w") or []),
    }


def _build_preview_admin_ops_status_view(bundle) -> dict[str, Any]:
    status = bundle.admin_ops_status.get("status") or {}
    freshness = (bundle.admin_ops_status.get("meta") or {}).get("freshness") or {}
    manifest = bundle.manifest or {}
    return {
        "status_cards": [
            {"label": "overall", "value": status.get("overall_status") or "-"},
            {"label": "bundle count", "value": status.get("bundle_count", 0)},
            {"label": "bundles ok", "value": status.get("bundles_ok", 0)},
            {"label": "asof", "value": freshness.get("asof") or bundle.asof or "-"},
        ],
        "recommendation": status.get("recommendation") or "-",
        "build_rows": [
            {"label": "bundle version", "value": manifest.get("bundle_version") or "-"},
            {"label": "schema version", "value": manifest.get("schema_version") or "-"},
            {"label": "built at", "value": manifest.get("built_at_utc") or "-"},
            {"label": "build status", "value": manifest.get("build_status") or "-"},
        ],
        "freshness_rows": [
            {"label": "DB mtime", "value": freshness.get("analytics_db_mtime_utc") or "-"},
            {"label": "latest week", "value": freshness.get("latest_week_end") or "-"},
            {
                "label": "latest change week",
                "value": freshness.get("latest_change_week_end") or "-",
            },
            {
                "label": "latest quality week",
                "value": freshness.get("latest_quality_week_end") or "-",
            },
        ],
    }


def _build_preview_bundle_health_view(bundle) -> dict[str, Any]:
    return {
        "bundle_rows": [
            {
                **row,
                "expected_pages_text": ", ".join(row.get("expected_pages") or []),
            }
            for row in bundle.bundle_health.get("bundles") or []
        ],
        "file_meta_rows": _preview_file_meta_rows(bundle.manifest.get("file_meta") or {}),
    }


def _build_admin_market_rank_history(rank_history: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for row in rank_history or []:
        asset_group = str(row.get("asset_group") or "-")
        grouped.setdefault(asset_group, []).append(str(row.get("strength_rank") or "-"))
    return {asset_group: " -> ".join(values[:6]) for asset_group, values in grouped.items()}


def _format_admin_market_number(value: Any, *, decimals: int = 0) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if decimals <= 0:
        return f"{numeric:,.0f}"
    return f"{numeric:,.{decimals}f}"


def _format_admin_market_metric_value(value: Any, unit: str | None = None) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    unit_text = str(unit or "").strip()
    if unit_text == "억원":
        return f"{numeric:,.0f}{unit_text}"
    return f"{numeric:,.2f}{unit_text}" if unit_text else f"{numeric:,.2f}"


def _build_admin_intraday_view(bundle) -> dict[str, Any]:
    summary = bundle.intraday_summary or {}
    detail = bundle.intraday_detail or {}
    state = detail.get("state") or {}
    signal_overlay = detail.get("signal_overlay") or summary.get("signal_overlay") or {}
    indexes = []
    for row in summary.get("indexes") or detail.get("indexes") or []:
        indexes.append(
            {
                "label": row.get("index_name") or row.get("index_code") or "-",
                "price_text": _format_admin_market_number(row.get("price"), decimals=2),
                "change_text": _format_percent(row.get("change_pct")),
            }
        )
    fx_rows = []
    for row in summary.get("fx") or detail.get("fx") or []:
        fx_rows.append(
            {
                "label": row.get("series_name") or row.get("series_code") or "-",
                "price_text": _format_admin_market_number(row.get("price"), decimals=2),
                "change_text": _format_percent(row.get("change_pct")),
            }
        )
    breadth_rows = []
    for row in detail.get("breadth") or []:
        breadth_rows.append(
            {
                "label": row.get("universe_code") or "-",
                "adv_dec_text": _format_admin_market_number(row.get("adv_dec_ratio"), decimals=2),
                "positive_ratio_text": _format_percent(row.get("positive_ratio")),
            }
        )
    futures_rows = []
    for row in summary.get("futures") or detail.get("futures") or []:
        futures_rows.append(
            {
                "contract_name": row.get("contract_name") or row.get("contract_code") or "-",
                "price_text": _format_admin_market_number(row.get("price"), decimals=2),
                "change_text": _format_percent(row.get("change_pct")),
                "volume_text": _format_admin_market_number(row.get("volume")),
                "relative_label": (
                    (signal_overlay.get("futures_overlay") or {}).get("relative_label") or "-"
                ),
            }
        )
    flow_rows = []
    for row in summary.get("flow_signals") or detail.get("flow_signals") or []:
        flow_rows.append(
            {
                "signal_name": row.get("signal_name") or row.get("signal_code") or "-",
                "metric_text": _format_admin_market_metric_value(
                    row.get("metric_value"),
                    row.get("metric_unit"),
                ),
                "direction_label": row.get("direction_label") or "-",
                "strength_label": row.get("strength_label") or "-",
            }
        )
    return {
        "enabled": bool(summary or detail),
        "asof": bundle.intraday_asof,
        "session_status": summary.get("session_status")
        or detail.get("session_status")
        or state.get("session_status")
        or "-",
        "direction_label": summary.get("direction_label") or state.get("direction_label") or "-",
        "total_score": (
            summary.get("total_score")
            if summary.get("total_score") is not None
            else state.get("total_score")
        ),
        "summary_line": summary.get("summary_line") or state.get("summary_line") or "-",
        "reference_close_date": summary.get("reference_close_date")
        or state.get("reference_close_date")
        or "-",
        "description": detail.get("description") or "장중 참고용 현재 지표 스냅샷입니다.",
        "notice": detail.get("notice") or "",
        "indexes": indexes,
        "fx_rows": fx_rows,
        "breadth_rows": breadth_rows,
        "futures_available": bool(signal_overlay.get("futures_available") or futures_rows),
        "flow_available": bool(signal_overlay.get("flow_available") or flow_rows),
        "futures_rows": futures_rows,
        "futures_overlay": signal_overlay.get("futures_overlay") or {},
        "flow_rows": flow_rows,
        "flow_messages": list((signal_overlay.get("flow_overlay") or {}).get("messages") or []),
        "futures_source": signal_overlay.get("futures_source")
        or (signal_overlay.get("futures_overlay") or {}).get("source")
        or "",
        "flow_source": signal_overlay.get("flow_source") or "",
    }


def _build_admin_market_lab_view(bundle) -> dict[str, Any]:
    timeline = bundle.timeline or {}
    asset_strength = bundle.asset_strength or {}
    state_transition = bundle.state_transition or {}
    model_background = bundle.model_background or {}
    rank_history_map = _build_admin_market_rank_history(asset_strength.get("rank_history") or [])
    current_assets = []
    for row in asset_strength.get("current_assets") or []:
        current_assets.append(
            {
                **row,
                "rank_history_text": rank_history_map.get(str(row.get("asset_group") or "-"), "-"),
            }
        )
    return {
        "asof": bundle.asof,
        "source_dir": bundle.source_dir,
        "manifest": bundle.manifest,
        "summary": {
            "state_label": model_background.get("state_label")
            or (timeline.get("current_state") or {}).get("state_label")
            or "-",
            "state_score": (
                model_background.get("state_score")
                if model_background.get("state_score") is not None
                else (timeline.get("current_state") or {}).get("state_score")
            ),
            "summary_line": model_background.get("summary_line") or "-",
            "reference_note": model_background.get("reference_note") or "-",
            "briefing_tone": model_background.get("briefing_tone") or "-",
        },
        "intraday": _build_admin_intraday_view(bundle),
        "background_points": [
            str(item).strip()
            for item in (model_background.get("model_background_points") or [])
            if str(item).strip()
        ],
        "favorable_signals": [
            str(item).strip()
            for item in (model_background.get("favorable_signals") or [])
            if str(item).strip()
        ],
        "caution_signals": [
            str(item).strip()
            for item in (model_background.get("caution_signals") or [])
            if str(item).strip()
        ],
        "top_assets": list(model_background.get("top_assets") or [])[:3],
        "bottom_assets": list(model_background.get("bottom_assets") or [])[:3],
        "timeline": {
            "current": timeline.get("current_state") or {},
            "points": list(timeline.get("points") or [])[-12:],
        },
        "asset_strength": {
            "current_assets": current_assets,
        },
        "state_transition": {
            "current": state_transition.get("current") or {},
            "recent_changes": list(state_transition.get("recent_changes") or [])[:16],
        },
        "raw_links": [
            {
                "label": "manifest",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="manifest"),
            },
            {
                "label": "timeline",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="timeline"),
            },
            {
                "label": "asset strength",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="asset_strength"),
            },
            {
                "label": "state transition",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="state_transition"),
            },
            {
                "label": "model background",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="model_background"),
            },
            {
                "label": "intraday manifest",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="intraday_manifest"),
            },
            {
                "label": "intraday summary",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="intraday_summary"),
            },
            {
                "label": "intraday detail",
                "href": url_for("admin_market_briefing_lab_raw", payload_key="intraday_detail"),
            },
        ],
    }


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    logger = configure_logging(settings.log_level)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = settings.session_secret_key
    provider = SnapshotDataProvider(settings)
    user_snapshot_api = UserSnapshotMockApi(settings)
    market_analysis_api = MarketAnalysisMockApi(settings)
    tseries_api = TSeriesOperationalApi(settings)
    trading_sign_api = TradingSignSnapshotApi(settings)
    analytics_preview_api = AnalyticsPreviewApi(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    analytics_preview_p2_api = AnalyticsPreviewP2Api(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    analytics_preview_p3_api = AnalyticsPreviewP3Api(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    analytics_preview_p4_api = AnalyticsPreviewP4Api(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    analytics_preview_p5_api = AnalyticsPreviewP5Api(
        cache_ttl_seconds=settings.snapshot_cache_ttl_seconds
    )
    admin_market_lab_api = AdminMarketLabApi(cache_ttl_seconds=settings.snapshot_cache_ttl_seconds)
    feedback_store = FeedbackStore(settings)
    access_store = AccessStore(settings)
    investment_status_service = InvestmentStatusService(settings, access_store)
    investment_portfolio_api = InvestmentPortfolioApi(settings=settings)
    admin_new_entries_api = AdminNewEntriesApi(settings)
    internal_models_api = InternalModelsApi(settings)
    valuation_ai_api = ValuationAiApi(settings)
    billing_service = BillingService(settings, access_store)

    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        access_store.ensure_bootstrap_admin(
            email=settings.bootstrap_admin_email,
            password=settings.bootstrap_admin_password,
        )
    for email in AUTO_ADMIN_EMAILS:
        if access_store.get_user_by_email(email) is not None:
            try:
                access_store.assign_role(email=email)
            except GrantValidationError:
                pass
    for email in AUTO_OPS_VIEWER_EMAILS:
        if access_store.get_user_by_email(email) is not None:
            try:
                access_store.assign_role(email=email, role_id="ops_viewer")
                if email in AUTO_OPS_VIEWER_ONLY_EMAILS:
                    access_store.revoke_role(email=email, role_id="admin")
            except GrantValidationError:
                pass

    app.config["SETTINGS"] = settings
    app.config["SNAPSHOT_PROVIDER"] = provider
    app.config["USER_SNAPSHOT_API"] = user_snapshot_api
    app.config["MARKET_ANALYSIS_API"] = market_analysis_api
    app.config["TSERIES_API"] = tseries_api
    app.config["TRADING_SIGN_API"] = trading_sign_api
    app.config["ANALYTICS_PREVIEW_API"] = analytics_preview_api
    app.config["ANALYTICS_PREVIEW_P2_API"] = analytics_preview_p2_api
    app.config["ANALYTICS_PREVIEW_P3_API"] = analytics_preview_p3_api
    app.config["ANALYTICS_PREVIEW_P4_API"] = analytics_preview_p4_api
    app.config["ANALYTICS_PREVIEW_P5_API"] = analytics_preview_p5_api
    app.config["ADMIN_MARKET_LAB_API"] = admin_market_lab_api
    app.config["FEEDBACK_STORE"] = feedback_store
    app.config["ACCESS_STORE"] = access_store
    app.config["INVESTMENT_STATUS_SERVICE"] = investment_status_service
    app.config["ADMIN_NEW_ENTRIES_API"] = admin_new_entries_api
    app.config["INTERNAL_MODELS_API"] = internal_models_api
    app.config["VALUATION_AI_API"] = valuation_ai_api
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

    def is_valid_form_csrf() -> bool:
        expected = session.get("csrf_token")
        provided = request.form.get("csrf_token", "")
        return bool(
            isinstance(expected, str)
            and expected
            and provided
            and secrets.compare_digest(provided, expected)
        )

    def require_csrf() -> None:
        if not is_valid_form_csrf():
            abort(400)

    def require_request_csrf() -> None:
        expected = session.get("csrf_token")
        provided = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not provided and request.is_json:
            payload = request.get_json(silent=True) or {}
            provided = str(payload.get("csrf_token") or "")
        if not expected or not provided or provided != expected:
            abort(400)

    def current_authenticated_access() -> AccessContext:
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            abort(401)
        return access_context

    def _private_headers() -> dict[str, str]:
        return {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Robots-Tag": "noindex, nofollow",
        }

    def _private_html_response(rendered: str) -> Response:
        response = Response(rendered, mimetype="text/html")
        response.headers.update(_private_headers())
        return response

    def _private_json_response(payload: dict[str, object], status: int = 200) -> Response:
        response = jsonify(payload)
        response.status_code = status
        response.headers.update(_private_headers())
        return response

    def _investment_prefill() -> dict[str, str]:
        return {
            "trade_date": request.args.get("trade_date", ""),
            "ticker": request.args.get("ticker", ""),
            "security_name": request.args.get("security_name", ""),
            "side": request.args.get("side", "buy"),
            "quantity": request.args.get("quantity", ""),
            "unit_price": request.args.get("unit_price", ""),
            "fee": request.args.get("fee", "0"),
        }

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

    def issue_login_email_verification(user: Any, next_url: str) -> str:
        verification_code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = (
            datetime.utcnow()
            + timedelta(seconds=settings.login_email_verification_code_ttl_seconds)
        ).isoformat()
        session["pending_login_email_verification"] = {
            "user_id": user.id,
            "email": str(user.email or "").strip().lower(),
            "code": verification_code,
            "expires_at": expires_at,
            "next_url": next_url,
            "attempts": 0,
        }
        if settings.login_email_verification_preview_enabled:
            session["login_email_verification_preview"] = verification_code
        else:
            session.pop("login_email_verification_preview", None)
        try:
            send_login_verification_email(
                settings=settings,
                to_email=str(user.email or "").strip(),
                code=verification_code,
            )
        except EmailDeliveryError:
            clear_login_email_verification()
            raise
        return verification_code

    def _pending_login_email_payload() -> dict[str, Any]:
        payload = session.get("pending_login_email_verification") or {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def is_login_email_verification_valid(verification_code: str) -> tuple[bool, str]:
        payload = _pending_login_email_payload()
        if not payload:
            return False, "expired"
        expires_at = payload.get("expires_at")
        try:
            expires = datetime.fromisoformat(str(expires_at or ""))
        except ValueError:
            return False, "expired"
        if datetime.utcnow() > expires:
            clear_login_email_verification()
            return False, "expired"

        if payload.get("code") != verification_code.strip():
            attempts = int(payload.get("attempts") or 0) + 1
            payload["attempts"] = attempts
            session["pending_login_email_verification"] = payload
            if attempts >= 5:
                clear_login_email_verification()
                return False, "expired"
            return False, "invalid"
        return True, ""

    def clear_login_email_verification() -> None:
        session.pop("pending_login_email_verification", None)
        session.pop("login_email_verification_preview", None)

    def complete_login(user: Any, next_url: str) -> Response:
        user_email = str(user.email or "").strip().lower()
        if user_email in AUTO_ADMIN_EMAILS:
            try:
                access_store.assign_role(email=user.email)
            except GrantValidationError:
                pass
        if user_email in AUTO_OPS_VIEWER_EMAILS:
            try:
                access_store.assign_role(email=user.email, role_id="ops_viewer")
                if user_email in AUTO_OPS_VIEWER_ONLY_EMAILS:
                    access_store.revoke_role(email=user.email, role_id="admin")
            except GrantValidationError:
                pass

        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(24)
        return redirect(next_url)

    def admin_url(endpoint: str) -> str:
        return url_for(endpoint)

    def can_access_internal_preview(access_context: AccessContext | None = None) -> bool:
        if not settings.internal_preview_enabled:
            return False
        access_context = access_context or current_access_context()
        if not access_context.is_admin:
            return False
        if settings.app_env != "production":
            return True
        allowed_emails = {email.lower() for email in settings.analytics_preview_allowed_emails}
        current_email = str((access_context.user.email if access_context.user else "")).lower()
        return current_email in allowed_emails

    def can_access_ops_viewer(access_context: AccessContext | None = None) -> bool:
        access_context = access_context or current_access_context()
        if not access_context.authenticated:
            return False
        if access_context.is_admin:
            return True
        if "ops_viewer" in set(access_context.roles or ()):
            return True
        current_email = (
            str((access_context.user.email if access_context.user else "")).strip().lower()
        )
        return current_email in AUTO_OPS_VIEWER_EMAILS

    def build_admin_links(access_context: AccessContext | None = None) -> dict[str, str]:
        links = {
            "dashboard": admin_url("admin_dashboard"),
            "users": admin_url("admin_users"),
            "grant": admin_url("admin_grant"),
            "plans": admin_url("admin_plans_entitlements"),
            "publish": admin_url("admin_publish_snapshots"),
            "new_entries": admin_url("admin_new_entries"),
            "internal_models": admin_url("admin_internal_models"),
            "valuation_ai": admin_url("admin_valuation_ai"),
            "feedback": admin_url("admin_feedback"),
            "metrics": admin_url("admin_metrics"),
            "audit": admin_url("admin_audit"),
        }
        if can_access_internal_preview(access_context):
            links["analytics_preview"] = admin_url("admin_analytics_preview")
        if can_access_internal_preview(access_context):
            links["market_briefing_lab"] = admin_url("admin_market_briefing_lab")
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
        if not can_access_internal_preview(access_context):
            abort(404)
        return access_context

    def require_ops_viewer_access() -> AccessContext:
        access_context = current_access_context()
        if not can_access_ops_viewer(access_context):
            abort(404)
        return access_context

    def _normalize_admin_new_entries_scope(value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in {"user", "internal", "tseries"} else "user"

    def _normalize_admin_new_entries_period(value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in {"4w", "8w", "all"} else "8w"

    def _normalize_admin_new_entries_event_type(scope: str, value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        allowed = EVENT_TYPE_OPTIONS_BY_SCOPE.get(scope, ())
        if candidate in allowed:
            return candidate
        return "new_entry"

    def _normalize_admin_new_entries_model(scope: str, value: str | None) -> str:
        candidate = str(value or "").strip()
        if scope == "user":
            normalized = candidate.lower()
            aliases = {"안정형": "stable", "균형형": "balanced", "성장형": "growth"}
            normalized = aliases.get(candidate, aliases.get(normalized, normalized))
            return normalized if normalized in USER_SCOPE_MODELS else ""
        if scope == "tseries":
            uppered = candidate.upper()
            if uppered == "T_STOCK_DISCOVERY":
                uppered = "T-STOCK-V01"
            if uppered == "T_ETF_DISCOVERY":
                uppered = "T-ETF-V01"
            return uppered if uppered in TSERIES_SCOPE_MODELS else ""
        uppered = candidate.upper()
        return uppered if uppered in INTERNAL_SCOPE_MODELS else ""

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
            "portfolio_structure": url_for("admin_preview_portfolio_structure"),
            "holding_lifecycle": url_for("admin_preview_holding_lifecycle"),
        }

    def load_analytics_preview_p2_bundle(force_refresh: bool = False):
        return analytics_preview_p2_api.load_bundle(force_refresh=force_refresh)

    def build_analytics_preview_p3_links() -> dict[str, str]:
        return {
            "model_quality": url_for("admin_preview_model_quality"),
            "weekly_briefing": url_for("admin_preview_weekly_briefing"),
        }

    def load_analytics_preview_p3_bundle(force_refresh: bool = False):
        return analytics_preview_p3_api.load_bundle(force_refresh=force_refresh)

    def build_analytics_preview_p4_links() -> dict[str, str]:
        return {
            "asset_exposure": url_for("admin_preview_asset_exposure_detail"),
            "change_impact": url_for("admin_preview_change_impact"),
        }

    def load_analytics_preview_p4_bundle(force_refresh: bool = False):
        return analytics_preview_p4_api.load_bundle(force_refresh=force_refresh)

    def build_analytics_preview_p5_links() -> dict[str, str]:
        return {
            "admin_ops_status": url_for("admin_preview_admin_ops_status"),
            "bundle_health": url_for("admin_preview_bundle_health"),
        }

    def load_analytics_preview_p5_bundle(force_refresh: bool = False):
        return analytics_preview_p5_api.load_bundle(force_refresh=force_refresh)

    def load_admin_market_lab_bundle(force_refresh: bool = False):
        return admin_market_lab_api.load_bundle(force_refresh=force_refresh)

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
            bundle = user_snapshot_api.load_bundle(force_refresh=False)
        except UserSnapshotLoadError:
            return None
        return _filter_public_user_bundle(bundle)

    def load_market_bundle_or_error():
        try:
            return market_analysis_api.load_bundle(force_refresh=False)
        except MarketAnalysisLoadError:
            return None

    def load_tseries_overview_or_none(force_refresh: bool = False):
        try:
            return tseries_api.load_overview(force_refresh=force_refresh)
        except TSeriesLoadError:
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
        ops_viewer_access = can_access_ops_viewer(access_context)
        return {
            "service_name": "redbot",
            "current_user": access_context.user,
            "access_context": access_context,
            "can_access_ops_viewer": ops_viewer_access,
            "can_access_admin": bool(access_context.is_admin),
            "ui_redesign_enabled": bool(settings.ui_redesign_enabled),
            "ui_theme_default": str(settings.ui_theme_default or "light"),
            "status_messages": STATUS_MESSAGES,
            "billing_enabled": settings.billing_enabled,
            "billing_messages": BILLING_MESSAGES,
            "csrf_token": get_csrf_token(),
            "policy_state": get_policy_state(settings),
            "profile_labels": {
                "stable": "안정형",
                "balanced": "균형형",
                "growth": "성장형",
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
    def apply_response_headers(response: Response) -> Response:
        is_https = (
            request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        )
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=2592000"
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
        return (jsonify(bundle.recommendation_today), 200)

    @app.get("/api/v1/model-weekly/<service_profile>")
    @app.get("/api/v1/model-snapshots/<service_profile>")
    def api_model_snapshot_by_profile(service_profile: str) -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        if not _is_public_service_profile(service_profile):
            return ({"status": "not_found", "message": "service profile not found"}, 404)
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

    @app.get("/api/v1/changes/history")
    def api_changes_history() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        payload = deepcopy(bundle.change_history)
        period = request.args.get("period", "").strip().lower()
        model = request.args.get("model", "").strip().lower()
        for period_key in ("weekly", "monthly"):
            filtered_period_rows = []
            for row in payload.get(period_key) or []:
                models = _filter_change_rows_by_model(row.get("models") or [], model)
                if model and not models:
                    continue
                filtered_row = dict(row)
                filtered_row["models"] = models
                filtered_period_rows.append(filtered_row)
            payload[period_key] = filtered_period_rows
        payload["history"] = [
            {
                **row,
                "changes": _filter_change_rows_by_model(row.get("changes") or [], model),
            }
            for row in payload.get("history") or []
            if not model or _filter_change_rows_by_model(row.get("changes") or [], model)
        ]
        if period in {"weekly", "monthly"}:
            payload["selected_period"] = period
            payload["items"] = payload.get(period) or []
        return (jsonify(payload), 200)

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

    @app.get("/api/v1/market-analysis/timeline")
    def api_market_analysis_timeline() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_timeline")), 200)

    @app.get("/api/v1/market-analysis/asset-strength")
    def api_market_analysis_asset_strength() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_asset_strength")), 200)

    @app.get("/api/v1/market-analysis/state-transition")
    def api_market_analysis_state_transition() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_state_transition")), 200)

    @app.get("/api/v1/market-analysis/model-background")
    def api_market_analysis_model_background() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_model_background")), 200)

    @app.get("/api/v1/market-analysis/next-day-preview")
    def api_market_analysis_next_day_preview() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_next_day_preview")), 200)

    @app.get("/api/v1/market-analysis/tabs")
    def api_market_analysis_tabs() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_analysis_tabs")), 200)

    @app.get("/api/v1/market-analysis/live-context")
    def api_market_analysis_live_context() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_live_context")), 200)

    @app.get("/api/v1/market-analysis/data-guide")
    def api_market_analysis_data_guide() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_data_guide")), 200)

    @app.get("/api/v1/market-analysis/dart-summary")
    def api_market_analysis_dart_summary() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_dart_summary")), 200)

    @app.get("/api/v1/market-analysis/breadth-detail")
    def api_market_analysis_breadth_detail() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_breadth_detail")), 200)

    @app.get("/api/v1/market-analysis/us-macro-panel")
    def api_market_analysis_us_macro_panel() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_us_macro_panel")), 200)

    @app.get("/api/v1/market-analysis/timeline/history")
    def api_market_analysis_timeline_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_timeline_history")), 200)

    @app.get("/api/v1/market-analysis/asset-strength/history")
    def api_market_analysis_asset_strength_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_asset_strength_history")), 200)

    @app.get("/api/v1/market-analysis/state-transition/history")
    def api_market_analysis_state_transition_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_state_transition_history")), 200)

    @app.get("/api/v1/market-analysis/next-day-preview/history")
    def api_market_analysis_next_day_preview_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_next_day_preview_history")), 200)

    @app.get("/api/v1/market-analysis/dart-summary/history")
    def api_market_analysis_dart_summary_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_dart_summary_history")), 200)

    @app.get("/api/v1/market-analysis/breadth-detail/history")
    def api_market_analysis_breadth_detail_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_breadth_detail_history")), 200)

    @app.get("/api/v1/market-analysis/us-macro-panel/history")
    def api_market_analysis_us_macro_panel_history() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market analysis unavailable"}, 503)
        return (jsonify(market_analysis_api.get_api_payload("api_us_macro_panel_history")), 200)

    @app.get("/api/v1/market-environment-indicators")
    def api_market_environment_indicators() -> tuple[dict[str, object], int]:
        payload = load_market_bundle_or_error()
        if payload is None:
            return ({"status": "error", "message": "market environment unavailable"}, 503)
        api_payload = market_analysis_api.get_api_payload("api_environment_indicators")
        if not api_payload:
            api_payload = market_analysis_api.get_api_payload("environment_indicators")
        return (jsonify(api_payload), 200)

    @app.get("/api/v1/discovery/t-series")
    def api_tseries_models() -> tuple[dict[str, object], int]:
        try:
            overview = tseries_api.load_overview(force_refresh=False)
        except TSeriesLoadError:
            return ({"status": "error", "message": "t-series unavailable"}, 503)
        return (
            jsonify(
                {
                    "models": tseries_api.list_model_summaries(force_refresh=False),
                    "source_name": overview.source_name,
                    "warnings": overview.warnings,
                    "errors": overview.errors,
                }
            ),
            200,
        )

    @app.get("/api/v1/discovery/t-series/<model_code>")
    def api_tseries_model_detail(model_code: str) -> tuple[dict[str, object], int]:
        try:
            snapshot = tseries_api.get_snapshot(model_code, force_refresh=False)
        except TSeriesLoadError:
            return ({"status": "not_found", "message": "t-series model not found"}, 404)
        if snapshot is None:
            return ({"status": "not_found", "message": "t-series model not found"}, 404)
        return (jsonify(snapshot), 200)

    def render_market_analysis_page(*, record_path: str) -> Response:
        market_bundle = load_market_bundle_or_error()
        market_status_snapshot = market_analysis_api.get_status(force_refresh=False)
        page_view = _build_market_page_view((market_bundle.page if market_bundle else {}))
        timeline_payload = (
            market_bundle.timeline_history or market_bundle.timeline if market_bundle else {}
        )
        asset_strength_payload = (
            market_bundle.asset_strength_history or market_bundle.asset_strength
            if market_bundle
            else {}
        )
        timeline_view = _build_market_timeline_view(timeline_payload)
        asset_strength_view = _build_market_asset_strength_view(asset_strength_payload)
        state_transition_view = _build_market_state_transition_view(
            market_bundle.state_transition if market_bundle else {}
        )
        model_background_view = _build_market_model_background_view(
            market_bundle.model_background if market_bundle else {}
        )
        record_page_view(record_path)
        return Response(
            render_template(
                "market_analysis.html",
                page_title=page_view.get("page_title", "시장 브리핑"),
                market_page_view=page_view,
                market_timeline_view=timeline_view,
                market_asset_strength_view=asset_strength_view,
                market_state_transition_view=state_transition_view,
                market_model_background_view=model_background_view,
                market_state_bar=page_view.get("state_bar"),
                market_state_bridge_view=page_view.get("state_intraday_bridge_view"),
                market_state_composite_view=page_view.get("market_state_composite_view"),
                market_status_snapshot=market_status_snapshot,
                market_next_day_preview_view=_build_market_next_day_preview_view(
                    market_bundle.next_day_preview if market_bundle else {}
                ),
                notice_blocks=_build_notice_blocks("market_brief", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/")
    def home() -> Response:
        return render_market_analysis_page(record_path="/")

    @app.get("/theme-preview")
    def theme_preview() -> Response:
        record_page_view("/theme-preview")
        return Response(
            render_template("theme_preview.html", page_title="Theme Preview"), mimetype="text/html"
        )

    @app.get("/redesign-preview")
    def redesign_preview() -> Response:
        record_page_view("/redesign-preview")
        return Response(
            render_template("redesign_preview.html", page_title="UI Redesign Preview"),
            mimetype="text/html",
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Response:
        next_url = _safe_next_url(request.values.get("next"))
        if request.method == "GET":
            record_page_view("/login")
            pending_payload = _pending_login_email_payload()
            pending_email = str(pending_payload.get("email") or "")
            preview_code = ""
            if pending_payload and settings.login_email_verification_preview_enabled:
                preview_code = str(session.get("login_email_verification_preview") or "")
            return Response(
                render_template(
                    "login.html",
                    page_title="로그인",
                    status=request.args.get("status", ""),
                    next_url=next_url,
                    verification_pending=bool(pending_payload),
                    pending_email=pending_email,
                    preview_code=preview_code,
                ),
                mimetype="text/html",
            )

        if not is_valid_form_csrf():
            if isinstance(session.get("user_id"), int):
                return redirect(next_url)
            abort(400)
        action = request.form.get("action", "password")
        if action == "verify_email_code":
            is_valid, reason = is_login_email_verification_valid(
                request.form.get("email_verification_code", "")
            )
            pending_payload = _pending_login_email_payload()
            pending_next_url = _safe_next_url(
                request.form.get("next") or str(pending_payload.get("next_url") or next_url)
            )
            if not is_valid:
                status = "email_code_expired" if reason == "expired" else "email_code_invalid"
                return redirect(url_for("login", status=status, next=pending_next_url))
            user = access_store.get_user_by_id(int(pending_payload.get("user_id") or 0))
            if user is None:
                clear_login_email_verification()
                return redirect(url_for("login", status="email_code_expired", next=next_url))
            clear_login_email_verification()
            return complete_login(user, pending_next_url)

        try:
            user = access_store.authenticate_local(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
            )
        except LoginValidationError:
            return redirect(url_for("login", status="invalid", next=next_url))
        if settings.login_email_verification_enabled:
            try:
                issue_login_email_verification(user, next_url)
            except EmailDeliveryError:
                return redirect(url_for("login", status="email_send_error", next=next_url))
            return redirect(url_for("login", status="email_code_sent", next=next_url))
        return complete_login(user, next_url)

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

    @app.get("/me/investments")
    def me_investments() -> Response:
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("me_investments")))
        active_tab = request.args.get("tab", "virtual").strip().lower()
        if active_tab not in INVESTMENT_ACCOUNT_LABELS:
            active_tab = "virtual"
        account_dashboards = {
            account_type: investment_status_service.list_dashboard(
                user_id=access_context.user.id,
                account_type=account_type,
                user_key=access_context.user.email,
            )
            for account_type in INVESTMENT_ACCOUNT_LABELS
        }
        performance_history = investment_status_service.list_performance_history(
            user_id=access_context.user.id,
            user_key=access_context.user.email,
        )
        active_performance_history = next(
            (
                row
                for row in performance_history.get("accounts", [])
                if row.get("account_type") == active_tab
            ),
            {},
        )
        dashboard = account_dashboards[active_tab]
        validation_feedback = None
        validation_status = request.args.get("validation_status", "")
        if validation_status:
            validation_feedback = {
                "status": validation_status,
                "message": request.args.get("validation_message", ""),
                "market": request.args.get("validation_market", ""),
            }
        status_key = request.args.get("status", "")
        return _private_html_response(
            render_template(
                "investments.html",
                page_title="투자 현황",
                page_robots="noindex, nofollow",
                active_tab=active_tab,
                investment_tabs=INVESTMENT_ACCOUNT_LABELS,
                dashboard=dashboard,
                account_dashboards=account_dashboards,
                performance_history=performance_history,
                active_performance_history=active_performance_history,
                form_values=_investment_prefill(),
                validation_feedback=validation_feedback,
                investment_status_key=status_key,
                investment_status_message=INVESTMENT_MESSAGES.get(status_key, ""),
            )
        )

    @app.post("/me/investments/validate-security")
    def me_investments_validate_security() -> Response:
        require_request_csrf()
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("me_investments")))
        account_type = request.form.get("account_type", "virtual")
        validation = investment_status_service.validate_security(
            ticker=request.form.get("ticker", ""),
            security_name=request.form.get("security_name", ""),
        )
        params = {
            "tab": account_type,
            "trade_date": request.form.get("trade_date", ""),
            "ticker": request.form.get("ticker", ""),
            "security_name": request.form.get("security_name", ""),
            "side": request.form.get("side", "buy"),
            "quantity": request.form.get("quantity", ""),
            "unit_price": request.form.get("unit_price", ""),
            "fee": request.form.get("fee", "0"),
            "validation_status": "valid" if validation.valid else "invalid",
            "validation_message": validation.message,
            "validation_market": validation.market or "",
        }
        return redirect(url_for("me_investments", **params))

    @app.post("/me/investments/transactions")
    def me_investments_transactions() -> Response:
        require_request_csrf()
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("me_investments")))
        account_type = request.form.get("account_type", "virtual")
        try:
            investment_status_service.create_transaction(
                user_id=access_context.user.id,
                user_key=access_context.user.email,
                account_type=account_type,
                trade_date=request.form.get("trade_date", ""),
                ticker=request.form.get("ticker", ""),
                security_name=request.form.get("security_name", ""),
                side=request.form.get("side", "buy"),
                quantity=request.form.get("quantity", ""),
                unit_price=request.form.get("unit_price", ""),
                fee=request.form.get("fee", "0"),
            )
        except InvestmentValidationError as exc:
            params = {
                "tab": account_type,
                "trade_date": request.form.get("trade_date", ""),
                "ticker": request.form.get("ticker", ""),
                "security_name": request.form.get("security_name", ""),
                "side": request.form.get("side", "buy"),
                "quantity": request.form.get("quantity", ""),
                "unit_price": request.form.get("unit_price", ""),
                "fee": request.form.get("fee", "0"),
                "status": "security_mismatch" if "일치하지 않습니다" in str(exc) else "invalid",
                "validation_status": "invalid",
                "validation_message": str(exc),
            }
            if "보유 수량보다 많은 매도" in str(exc):
                params["status"] = "insufficient_holdings"
            return redirect(url_for("me_investments", **params))
        return redirect(url_for("me_investments", tab=account_type, status="saved"))

    @app.post("/me/investments/transactions/<int:transaction_id>")
    def me_investments_transaction_update(transaction_id: int) -> Response:
        require_request_csrf()
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("me_investments")))
        account_type = request.form.get("account_type", "virtual")
        try:
            investment_status_service.update_transaction(
                user_id=access_context.user.id,
                user_key=access_context.user.email,
                account_type=account_type,
                transaction_id=transaction_id,
                trade_date=request.form.get("trade_date", ""),
                ticker=request.form.get("ticker", ""),
                security_name=request.form.get("security_name", ""),
                side=request.form.get("side", "buy"),
                quantity=request.form.get("quantity", ""),
                unit_price=request.form.get("unit_price", ""),
                fee=request.form.get("fee", "0"),
            )
        except InvestmentValidationError as exc:
            params = {
                "tab": account_type,
                "status": "security_mismatch" if "일치하지 않습니다" in str(exc) else "invalid",
                "validation_status": "invalid",
                "validation_message": str(exc),
            }
            if "보유 수량보다 많은 매도" in str(exc):
                params["status"] = "insufficient_holdings"
            return redirect(url_for("me_investments", **params))
        return redirect(url_for("me_investments", tab=account_type, status="updated"))

    @app.get("/api/v1/me/investments/<account_type>")
    def api_me_investments(account_type: str) -> Response:
        access_context = current_authenticated_access()
        try:
            dashboard = investment_status_service.list_dashboard(
                user_id=access_context.user.id,
                account_type=account_type,
                user_key=access_context.user.email,
            )
        except InvestmentValidationError:
            return _private_json_response(
                {"status": "error", "message": "invalid account type"},
                400,
            )
        return _private_json_response(dashboard, 200)

    @app.get("/api/v1/me/investments/history")
    def api_me_investments_history() -> Response:
        access_context = current_authenticated_access()
        history = investment_status_service.list_performance_history(
            user_id=access_context.user.id,
            user_key=access_context.user.email,
        )
        return _private_json_response(history, 200)

    @app.post("/api/v1/me/investments/validate-security")
    def api_me_investments_validate_security() -> Response:
        current_authenticated_access()
        require_request_csrf()
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        validation = investment_status_service.validate_security(
            ticker=str(payload.get("ticker") or ""),
            security_name=str(payload.get("security_name") or ""),
        )
        return _private_json_response(
            {
                "valid": validation.valid,
                "ticker": validation.ticker,
                "security_name": validation.security_name,
                "market": validation.market,
                "asset_type": validation.asset_type,
                "message": validation.message,
            },
            200,
        )

    @app.post("/api/v1/me/investments/transactions")
    def api_me_investments_transactions() -> Response:
        access_context = current_authenticated_access()
        require_request_csrf()
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        try:
            transaction = investment_status_service.create_transaction(
                user_id=access_context.user.id,
                user_key=access_context.user.email,
                account_type=str(payload.get("account_type") or "virtual"),
                trade_date=str(payload.get("trade_date") or ""),
                ticker=str(payload.get("ticker") or ""),
                security_name=str(payload.get("security_name") or ""),
                side=str(payload.get("side") or "buy"),
                quantity=str(payload.get("quantity") or ""),
                unit_price=str(payload.get("unit_price") or ""),
                fee=str(payload.get("fee") or "0"),
            )
        except InvestmentValidationError as exc:
            return _private_json_response({"status": "error", "message": str(exc)}, 400)
        return _private_json_response({"status": "ok", "transaction": transaction}, 201)

    @app.post("/api/v1/me/investments/transactions/<int:transaction_id>")
    def api_me_investments_transaction_update(transaction_id: int) -> Response:
        access_context = current_authenticated_access()
        require_request_csrf()
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        try:
            transaction = investment_status_service.update_transaction(
                user_id=access_context.user.id,
                user_key=access_context.user.email,
                account_type=str(payload.get("account_type") or "virtual"),
                transaction_id=transaction_id,
                trade_date=str(payload.get("trade_date") or ""),
                ticker=str(payload.get("ticker") or ""),
                security_name=str(payload.get("security_name") or ""),
                side=str(payload.get("side") or "buy"),
                quantity=str(payload.get("quantity") or ""),
                unit_price=str(payload.get("unit_price") or ""),
                fee=str(payload.get("fee") or "0"),
            )
        except InvestmentValidationError as exc:
            return _private_json_response({"status": "error", "message": str(exc)}, 400)
        return _private_json_response({"status": "ok", "transaction": transaction}, 200)

    @app.get("/investment-portfolio")
    def investment_portfolio() -> Response:
        require_ops_viewer_access()
        try:
            bundle = investment_portfolio_api.load_bundle()
        except InvestmentPortfolioLoadError:
            return Response(
                render_template(
                    "snapshot_unavailable.html",
                    page_title="투자 포트폴리오",
                    message="투자 포트폴리오 데이터가 아직 준비되지 않았습니다.",
                ),
                status=503,
                mimetype="text/html",
            )
        return Response(
            render_template(
                "investment_portfolio.html",
                page_title="투자 포트폴리오",
                page_robots="noindex, nofollow",
                portfolio=bundle.view,
            ),
            mimetype="text/html",
        )

    @app.get("/api/v1/investment-portfolio")
    def api_investment_portfolio() -> Response:
        require_ops_viewer_access()
        try:
            bundle = investment_portfolio_api.load_bundle()
        except InvestmentPortfolioLoadError:
            return _private_json_response(
                {"status": "error", "message": "portfolio unavailable"},
                503,
            )
        return _private_json_response(bundle.payload, 200)

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
        market_state_bar = _build_market_state_bar_from_bundle(market_bundle)
        today_payload = market_bundle.today if market_bundle else {}
        today_market_bridge = today_payload.get("market_bridge") or {}
        model_lookup = {
            model.get("service_profile"): model for model in bundle.user_models.get("models", [])
        }
        report_views = [
            _build_today_report_view(
                report, current_market_regime, model_lookup.get(report.get("service_profile"))
            )
            for report in bundle.recommendation_today.get("reports", [])
        ]
        trading_sign_status = trading_sign_api.get_status(force_refresh=False)
        trading_sign_model_map: dict[str, dict[str, Any]] = {}
        if trading_sign_status.snapshot_accessible:
            try:
                trading_sign_model_map = trading_sign_api.get_model_detail_map(force_refresh=False)
            except TradingSignLoadError:
                trading_sign_model_map = {}
        for report in report_views:
            service_profile = str(report.get("service_profile") or "").strip().lower()
            trading_model_code = TRADING_SIGN_MODEL_CODE_BY_PROFILE.get(service_profile, "")
            report["trading_sign_view"] = _build_trading_sign_view(
                service_profile,
                trading_sign_model_map.get(trading_model_code),
                trading_sign_status,
            )
            report["redesign_chart_view"] = _build_today_performance_chart_view(
                report.get("period_view")
            )
            safe_record_event(
                event_name="model_section_view",
                page="/today",
                model_id=report.get("service_profile"),
            )
        return Response(
            render_template(
                "today.html",
                page_title="전략별 퀀트모델",
                bundle=bundle,
                status_snapshot=_apply_public_status_counts(
                    user_snapshot_api.get_status(force_refresh=False), bundle
                ),
                report_views=report_views,
                market_today_payload=today_payload,
                market_today_background_view=_build_market_today_background_view(
                    market_bundle.model_background if market_bundle else {}
                ),
                market_state_bar=market_state_bar,
                market_state_bridge_view=_build_market_state_bridge_view(
                    today_market_bridge.get("state_intraday_bridge"),
                    fallback_bar=market_state_bar,
                    asof=today_payload.get("asof") or getattr(market_bundle, "asof", None),
                ),
                market_state_composite_view=_build_market_state_composite_view(
                    today_market_bridge.get("market_state_composite")
                ),
                market_status_snapshot=market_analysis_api.get_status(force_refresh=False),
                market_next_day_preview_view=_build_market_next_day_preview_view(
                    market_bundle.next_day_preview if market_bundle else {}
                ),
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
        user_status_snapshot = _apply_public_status_counts(
            user_snapshot_api.get_status(force_refresh=False), bundle
        )
        maybe_alert_status(user_status_snapshot)
        publish_status_payload = None
        if user_status_snapshot.snapshot_accessible:
            publish_status_payload = user_snapshot_api.get_publish_status(force_refresh=False)
        selected_period = request.args.get("period", "weekly").strip().lower()
        if selected_period not in {"weekly", "monthly"}:
            selected_period = "weekly"
        selected_model = _normalize_change_model_filter(request.args.get("model"))
        return Response(
            render_template(
                "changes.html",
                page_title="변경내역",
                bundle=bundle,
                status_snapshot=user_status_snapshot,
                publish_status_payload=publish_status_payload,
                change_rows=bundle.recent_changes.get("changes", []),
                change_history_rows=_build_change_history_rows(
                    bundle.change_history,
                    period=selected_period,
                    model=selected_model,
                ),
                selected_change_period=selected_period,
                selected_change_model=selected_model,
                change_model_filters=[
                    {"label": "전체", "value": ""},
                    {"label": "안정형", "value": "stable"},
                    {"label": "균형형", "value": "balanced"},
                    {"label": "성장형", "value": "growth"},
                ],
            ),
            mimetype="text/html",
        )

    @app.get("/market-analysis")
    def market_analysis() -> Response:
        return render_market_analysis_page(record_path="/market-analysis")

    @app.get("/market-analysis/data")
    def market_analysis_data() -> Response:
        market_bundle = load_market_bundle_or_error()
        market_status_snapshot = market_analysis_api.get_status(force_refresh=False)
        analysis_view = _build_market_analysis_data_view(market_bundle)
        record_page_view("/market-analysis/data")
        return Response(
            render_template(
                "market_analysis_data.html",
                page_title="시장 분석",
                analysis_view=analysis_view,
                market_status_snapshot=market_status_snapshot,
                notice_blocks=_build_notice_blocks("market_brief", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/market-environment-indicators")
    def market_environment_indicators() -> Response:
        market_bundle = load_market_bundle_or_error()
        market_status_snapshot = market_analysis_api.get_status(force_refresh=False)
        environment_view = _build_market_environment_indicators_view(
            market_bundle.environment_indicators if market_bundle else {}
        )
        record_page_view("/market-environment-indicators")
        return Response(
            render_template(
                "market_environment_indicators.html",
                page_title="시장 환경 지표",
                environment_view=environment_view,
                market_status_snapshot=market_status_snapshot,
                notice_blocks=_build_notice_blocks("market_brief", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/discovery")
    def discovery() -> Response | tuple[str, int]:
        require_ops_viewer_access()
        try:
            overview = tseries_api.load_overview(force_refresh=False)
        except TSeriesLoadError:
            return (
                render_template(
                    "error.html",
                    page_title="상승종목 발굴 데이터 오류",
                    status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                    metrics_summary=safe_metrics_summary(),
                    message=(
                        "현재 상승종목 발굴 데이터를 불러오지 못했습니다. "
                        "잠시 후 다시 시도해 주세요."
                    ),
                ),
                503,
            )
        trading_sign_status = trading_sign_api.get_status(force_refresh=False)
        trading_sign_model_map: dict[str, dict[str, Any]] = {}
        if trading_sign_status.snapshot_accessible:
            try:
                trading_sign_model_map = trading_sign_api.get_model_detail_map(force_refresh=False)
            except TradingSignLoadError:
                trading_sign_model_map = {}

        discovery_models = []
        for model in overview.models:
            model_view = dict(model)
            trading_model_code = T_SERIES_TRADING_SIGN_MODEL_CODE_BY_MODEL.get(
                model_view.get("model_code", "")
            )
            model_view["trading_sign_view"] = _build_trading_sign_view(
                str(model_view.get("model_code") or ""),
                trading_sign_model_map.get(trading_model_code or ""),
                trading_sign_status,
                fallback_message=TRADING_SIGN_DISCOVERY_FALLBACK_TEXT,
                preferred_section_keys=("recommended", "held"),
                include_empty_sections=False,
            )
            discovery_models.append(model_view)

        record_page_view("/discovery")
        return Response(
            render_template(
                "discovery.html",
                page_title="상승종목 발굴",
                discovery_models=discovery_models,
                discovery_warnings=overview.warnings,
                discovery_errors=overview.errors,
                discovery_source_name=overview.source_name,
                tseries_bucket_labels=T_SERIES_BUCKET_LABELS,
                tseries_asset_scope_labels=T_SERIES_ASSET_SCOPE_LABELS,
                tseries_etf_role_labels=T_SERIES_ETF_ROLE_LABELS,
                tseries_watch_status_labels=T_SERIES_WATCH_STATUS_LABELS,
                tseries_watch_tier_labels=T_SERIES_WATCH_TIER_LABELS,
                notice_blocks=_build_notice_blocks("service_nature", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

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
                admin_links=build_admin_links(access_context),
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
                admin_links=build_admin_links(access_context),
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
                admin_links=build_admin_links(access_context),
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
                admin_links=build_admin_links(access_context),
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
                admin_links=build_admin_links(access_context),
                status=request.args.get("status", ""),
                status_snapshot=provider.get_status(force_refresh=False),
                published_rows=build_published_snapshot_rows(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-preview")
    def admin_analytics_preview() -> Response:
        access_context = require_internal_preview_access()
        return Response(
            render_template(
                "admin/analytics_preview.html",
                page_title="Analytics Preview",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                preview_groups=[
                    {
                        "title": "1차 묶음",
                        "description": (
                            "오늘의 모델 정보, 모델 변화, 모델 비교 preview를 "
                            "한 번에 검토합니다."
                        ),
                        "links": [
                            {
                                "label": "오늘의 모델 정보",
                                "href": url_for("admin_preview_today_model_info"),
                            },
                            {"label": "모델 변화", "href": url_for("admin_preview_model_changes")},
                            {"label": "모델 비교", "href": url_for("admin_preview_model_compare")},
                        ],
                    },
                    {
                        "title": "2차 묶음",
                        "description": (
                            "포트폴리오 구조와 보유 종목 이력 preview를 함께 검토합니다."
                        ),
                        "links": [
                            {
                                "label": "포트폴리오 구조",
                                "href": url_for("admin_preview_portfolio_structure"),
                            },
                            {
                                "label": "보유 종목 이력",
                                "href": url_for("admin_preview_holding_lifecycle"),
                            },
                        ],
                    },
                    {
                        "title": "3차 묶음",
                        "description": ("모델 품질과 주간 브리핑 preview를 함께 검토합니다."),
                        "links": [
                            {
                                "label": "모델 품질",
                                "href": url_for("admin_preview_model_quality"),
                            },
                            {
                                "label": "주간 브리핑",
                                "href": url_for("admin_preview_weekly_briefing"),
                            },
                        ],
                    },
                    {
                        "title": "4차 묶음",
                        "description": ("자산 노출 상세와 변화 영향 preview를 함께 검토합니다."),
                        "links": [
                            {
                                "label": "자산 노출 상세",
                                "href": url_for("admin_preview_asset_exposure_detail"),
                            },
                            {
                                "label": "변화 영향",
                                "href": url_for("admin_preview_change_impact"),
                            },
                        ],
                    },
                    {
                        "title": "5차 묶음",
                        "description": (
                            "admin 운영 상태와 bundle health preview를 함께 검토합니다."
                        ),
                        "links": [
                            {
                                "label": "Admin 운영 상태",
                                "href": url_for("admin_preview_admin_ops_status"),
                            },
                            {
                                "label": "Bundle Health",
                                "href": url_for("admin_preview_bundle_health"),
                            },
                        ],
                    },
                ],
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

    @app.get("/admin/analytics-p3")
    def admin_preview_p3_root() -> Response:
        require_internal_preview_access()
        return redirect(url_for("admin_preview_model_quality"))

    @app.get("/admin/analytics-p3/model-quality")
    def admin_preview_model_quality() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p3_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP3LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p3_links(),
                    preview_title="모델 품질 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_model_quality_view(model)
            for model in preview_bundle.model_quality.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_model_quality.html",
                page_title="모델 품질 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p3_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p3/weekly-briefing")
    def admin_preview_weekly_briefing() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p3_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP3LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p3_links(),
                    preview_title="주간 브리핑 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_weekly_briefing_view(model)
            for model in preview_bundle.weekly_briefing.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_weekly_briefing.html",
                page_title="주간 브리핑 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p3_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p4")
    def admin_preview_p4_root() -> Response:
        require_internal_preview_access()
        return redirect(url_for("admin_preview_asset_exposure_detail"))

    @app.get("/admin/analytics-p4/asset-exposure-detail")
    def admin_preview_asset_exposure_detail() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p4_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP4LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p4_links(),
                    preview_title="자산 노출 상세 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_asset_exposure_detail_view(model)
            for model in preview_bundle.asset_exposure_detail.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_asset_exposure_detail.html",
                page_title="자산 노출 상세 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p4_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p4/change-impact")
    def admin_preview_change_impact() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p4_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP4LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p4_links(),
                    preview_title="변화 영향 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        model_views = [
            _build_preview_change_impact_view(model)
            for model in preview_bundle.change_impact.get("models", [])
        ]
        return Response(
            render_template(
                "analytics_preview_change_impact.html",
                page_title="변화 영향 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p4_links(),
                preview_bundle=preview_bundle,
                model_views=model_views,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p5")
    def admin_preview_p5_root() -> Response:
        require_internal_preview_access()
        return redirect(url_for("admin_preview_admin_ops_status"))

    @app.get("/admin/analytics-p5/admin-ops-status")
    def admin_preview_admin_ops_status() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p5_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP5LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p5_links(),
                    preview_title="Admin 운영 상태 preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        return Response(
            render_template(
                "analytics_preview_admin_ops_status.html",
                page_title="Admin 운영 상태 preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p5_links(),
                preview_bundle=preview_bundle,
                **_build_preview_admin_ops_status_view(preview_bundle),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/analytics-p5/bundle-health")
    def admin_preview_bundle_health() -> Response:
        require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            preview_bundle = load_analytics_preview_p5_bundle(force_refresh=force_refresh)
        except AnalyticsPreviewP5LoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="내부 preview 오류",
                    page_robots="noindex, nofollow",
                    preview_links=build_analytics_preview_p5_links(),
                    preview_title="Bundle Health preview",
                    message="내부 preview 데이터를 읽지 못했습니다.",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        return Response(
            render_template(
                "analytics_preview_bundle_health.html",
                page_title="Bundle Health preview",
                page_robots="noindex, nofollow",
                preview_links=build_analytics_preview_p5_links(),
                preview_bundle=preview_bundle,
                **_build_preview_bundle_health_view(preview_bundle),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/market-briefing-lab")
    def admin_market_briefing_lab() -> Response:
        access_context = require_internal_preview_access()
        force_refresh = request.args.get("refresh") == "1"
        try:
            market_lab_bundle = load_admin_market_lab_bundle(force_refresh=force_refresh)
        except AdminMarketLabLoadError as exc:
            return Response(
                render_template(
                    "analytics_preview_error.html",
                    page_title="admin market data unavailable",
                    page_robots="noindex, nofollow",
                    preview_title="시장 브리핑 Lab",
                    message="admin market data unavailable",
                    errors=exc.errors,
                ),
                status=503,
                mimetype="text/html",
            )
        return Response(
            render_template(
                "admin_market_briefing_lab.html",
                page_title="시장 브리핑 Lab",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                market_lab=_build_admin_market_lab_view(market_lab_bundle),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/market-briefing-lab/raw/<payload_key>")
    def admin_market_briefing_lab_raw(payload_key: str):
        require_internal_preview_access()
        bundle = load_admin_market_lab_bundle(force_refresh=request.args.get("refresh") == "1")
        payload_map = {
            "manifest": bundle.manifest,
            "timeline": bundle.timeline,
            "asset_strength": bundle.asset_strength,
            "state_transition": bundle.state_transition,
            "model_background": bundle.model_background,
            "intraday_manifest": bundle.intraday_manifest,
            "intraday_summary": bundle.intraday_summary,
            "intraday_detail": bundle.intraday_detail,
        }
        payload = payload_map.get(payload_key)
        if payload is None:
            abort(404)
        return jsonify(payload)

    @app.get("/admin/new-entries")
    def admin_new_entries() -> Response:
        access_context = require_admin_access()
        selected_scope = _normalize_admin_new_entries_scope(request.args.get("scope"))
        selected_event_type = _normalize_admin_new_entries_event_type(
            selected_scope,
            request.args.get("event_type"),
        )
        selected_period = _normalize_admin_new_entries_period(request.args.get("period"))
        selected_model = _normalize_admin_new_entries_model(
            selected_scope,
            request.args.get("model"),
        )
        payload = admin_new_entries_api.get_payload(
            scope=selected_scope,
            event_type=selected_event_type,
            period=selected_period,
            model=selected_model,
            force_refresh=request.args.get("refresh") == "1",
        )
        return Response(
            render_template(
                "admin/new_entries.html",
                page_title="신규 편입 추적",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                payload=payload,
                selected_scope=selected_scope,
                selected_event_type=selected_event_type,
                selected_period=selected_period,
                selected_model=selected_model,
                scope_options=[
                    {"value": "user", "label": "사용자용"},
                    {"value": "internal", "label": "내부용"},
                    {"value": "tseries", "label": "T-series"},
                ],
                event_type_options=[
                    {"value": "new_entry", "label": "신규 편입"},
                    {"value": "re_entry", "label": "재편입"},
                    {"value": "new_or_re_entry", "label": "신규 편입+재편입"},
                    {"value": "promotion", "label": "승격"},
                    {"value": "weight_increase", "label": "비중 증가"},
                ],
                period_options=[
                    {"value": "4w", "label": "최근 4주"},
                    {"value": "8w", "label": "최근 8주"},
                    {"value": "all", "label": "전체"},
                ],
                model_options_by_scope={
                    "user": [
                        {"value": "", "label": "전체"},
                        *[
                            {"value": code, "label": USER_MODEL_LABELS.get(code, code)}
                            for code in USER_SCOPE_MODELS
                        ],
                    ],
                    "internal": [
                        {"value": "", "label": "전체"},
                        *[{"value": code, "label": code} for code in INTERNAL_SCOPE_MODELS],
                    ],
                    "tseries": [
                        {"value": "", "label": "전체"},
                        *[{"value": code, "label": code} for code in TSERIES_SCOPE_MODELS],
                    ],
                },
                model_options=(
                    [{"value": "", "label": "전체"}]
                    + (
                        [
                            {"value": code, "label": USER_MODEL_LABELS.get(code, code)}
                            for code in USER_SCOPE_MODELS
                        ]
                        if selected_scope == "user"
                        else (
                            [{"value": code, "label": code} for code in INTERNAL_SCOPE_MODELS]
                            if selected_scope == "internal"
                            else [{"value": code, "label": code} for code in TSERIES_SCOPE_MODELS]
                        )
                    )
                ),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/internal-models")
    def admin_internal_models() -> Response:
        access_context = require_admin_access()
        bundle = internal_models_api.load_bundle(force_refresh=request.args.get("refresh") == "1")
        return Response(
            render_template(
                "admin/internal_models.html",
                page_title="내부용 모델",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                bundle=bundle,
                model_codes=INTERNAL_ADMIN_MODEL_CODES,
            ),
            mimetype="text/html",
        )

    @app.get("/api/v1/admin/internal-models")
    def api_admin_internal_models() -> tuple[dict[str, Any], int]:
        require_admin_access()
        bundle = internal_models_api.load_bundle(force_refresh=request.args.get("refresh") == "1")
        return (
            jsonify(
                {
                    "source_name": bundle.source_name,
                    "as_of_date": bundle.as_of_date,
                    "generated_at": bundle.generated_at,
                    "models": bundle.models,
                    "errors": bundle.errors,
                }
            ),
            200,
        )

    @app.get("/admin/valuation-ai")
    @app.get("/admin/ai-learning-models")
    def admin_valuation_ai() -> Response:
        access_context = require_admin_access()
        selected_scope = str(request.args.get("scope") or "").strip()
        selected_model_code = str(request.args.get("model_code") or "").strip()
        selected_challenger_state = str(request.args.get("challenger_state") or "").strip()
        selected_challenger_change_label = str(
            request.args.get("challenger_change_label") or ""
        ).strip()
        selected_risk_tag = str(request.args.get("risk_tag") or "").strip()
        selected_theme_bucket = str(request.args.get("theme_bucket") or "").strip()
        bundle = valuation_ai_api.load_bundle(
            scope=selected_scope,
            model_code=selected_model_code,
            challenger_state=selected_challenger_state,
            challenger_change_label=selected_challenger_change_label,
            risk_tag=selected_risk_tag,
            theme_bucket=selected_theme_bucket,
            force_refresh=request.args.get("refresh") == "1",
        )
        return Response(
            render_template(
                "admin/valuation_ai.html",
                page_title="AI 학습 모델",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                bundle=bundle,
                selected_scope=selected_scope,
                selected_model_code=selected_model_code,
                selected_challenger_state=selected_challenger_state,
                selected_challenger_change_label=selected_challenger_change_label,
                selected_risk_tag=selected_risk_tag,
                selected_theme_bucket=selected_theme_bucket,
            ),
            mimetype="text/html",
        )

    @app.get("/api/v1/admin/valuation-ai")
    @app.get("/api/v1/admin/ai-learning-models")
    def api_admin_valuation_ai() -> tuple[dict[str, Any], int]:
        require_admin_access()
        bundle = valuation_ai_api.load_bundle(
            scope=str(request.args.get("scope") or "").strip(),
            model_code=str(request.args.get("model_code") or "").strip(),
            challenger_state=str(request.args.get("challenger_state") or "").strip(),
            challenger_change_label=str(request.args.get("challenger_change_label") or "").strip(),
            risk_tag=str(request.args.get("risk_tag") or "").strip(),
            theme_bucket=str(request.args.get("theme_bucket") or "").strip(),
            force_refresh=request.args.get("refresh") == "1",
        )
        return (
            jsonify(
                {
                    "source_name": bundle.source_name,
                    "as_of_date": bundle.as_of_date,
                    "generated_at": bundle.generated_at,
                    "model_code": bundle.model_code,
                    "models": bundle.models,
                    "details": bundle.details,
                    "summary_cards": bundle.summary_cards,
                    "candidates": bundle.candidates,
                    "performance_summary": bundle.performance_summary,
                    "performance_detail": bundle.performance_detail,
                    "errors": bundle.errors,
                }
            ),
            200,
        )

    @app.get("/api/v1/admin/new-entries")
    def api_admin_new_entries() -> tuple[dict[str, Any], int]:
        require_admin_access()
        selected_scope = _normalize_admin_new_entries_scope(request.args.get("scope"))
        selected_event_type = _normalize_admin_new_entries_event_type(
            selected_scope,
            request.args.get("event_type"),
        )
        selected_period = _normalize_admin_new_entries_period(request.args.get("period"))
        selected_model = _normalize_admin_new_entries_model(
            selected_scope,
            request.args.get("model"),
        )
        payload = admin_new_entries_api.get_payload(
            scope=selected_scope,
            event_type=selected_event_type,
            period=selected_period,
            model=selected_model,
            force_refresh=request.args.get("refresh") == "1",
        )
        return (
            jsonify(
                {
                    "scope": payload.scope,
                    "event_type": payload.event_type,
                    "period": payload.period,
                    "model": payload.model,
                    "as_of_date": payload.as_of_date,
                    "generated_at": payload.generated_at,
                    "source_name": payload.source_name,
                    "summary": payload.summary,
                    "total_count": payload.total_count,
                    "rows": payload.rows,
                    "weekly_rankings_total_count": payload.weekly_rankings_total_count,
                    "weekly_rankings": payload.weekly_rankings,
                    "actual_live_performance": payload.actual_live_performance,
                    "errors": payload.errors,
                }
            ),
            200,
        )

    @app.get("/api/v1/admin/new-entries/user")
    def api_admin_new_entries_user() -> tuple[dict[str, Any], int]:
        require_admin_access()
        payload = admin_new_entries_api.get_payload(
            scope="user",
            event_type=_normalize_admin_new_entries_event_type(
                "user",
                request.args.get("event_type"),
            ),
            period=_normalize_admin_new_entries_period(request.args.get("period")),
            model=_normalize_admin_new_entries_model("user", request.args.get("model")),
            force_refresh=request.args.get("refresh") == "1",
        )
        return (
            jsonify(
                {
                    "scope": payload.scope,
                    "event_type": payload.event_type,
                    "period": payload.period,
                    "model": payload.model,
                    "as_of_date": payload.as_of_date,
                    "generated_at": payload.generated_at,
                    "source_name": payload.source_name,
                    "summary": payload.summary,
                    "total_count": payload.total_count,
                    "rows": payload.rows,
                    "weekly_rankings_total_count": payload.weekly_rankings_total_count,
                    "weekly_rankings": payload.weekly_rankings,
                    "actual_live_performance": payload.actual_live_performance,
                    "errors": payload.errors,
                }
            ),
            200,
        )

    @app.get("/api/v1/admin/new-entries/internal")
    def api_admin_new_entries_internal() -> tuple[dict[str, Any], int]:
        require_admin_access()
        payload = admin_new_entries_api.get_payload(
            scope="internal",
            event_type=_normalize_admin_new_entries_event_type(
                "internal",
                request.args.get("event_type"),
            ),
            period=_normalize_admin_new_entries_period(request.args.get("period")),
            model=_normalize_admin_new_entries_model("internal", request.args.get("model")),
            force_refresh=request.args.get("refresh") == "1",
        )
        return (
            jsonify(
                {
                    "scope": payload.scope,
                    "event_type": payload.event_type,
                    "period": payload.period,
                    "model": payload.model,
                    "as_of_date": payload.as_of_date,
                    "generated_at": payload.generated_at,
                    "source_name": payload.source_name,
                    "summary": payload.summary,
                    "total_count": payload.total_count,
                    "rows": payload.rows,
                    "weekly_rankings_total_count": payload.weekly_rankings_total_count,
                    "weekly_rankings": payload.weekly_rankings,
                    "actual_live_performance": payload.actual_live_performance,
                    "errors": payload.errors,
                }
            ),
            200,
        )

    @app.get("/api/v1/admin/new-entries/tseries")
    def api_admin_new_entries_tseries() -> tuple[dict[str, Any], int]:
        require_admin_access()
        payload = admin_new_entries_api.get_payload(
            scope="tseries",
            event_type=_normalize_admin_new_entries_event_type(
                "tseries",
                request.args.get("event_type"),
            ),
            period=_normalize_admin_new_entries_period(request.args.get("period")),
            model=_normalize_admin_new_entries_model("tseries", request.args.get("model")),
            force_refresh=request.args.get("refresh") == "1",
        )
        return (
            jsonify(
                {
                    "scope": payload.scope,
                    "event_type": payload.event_type,
                    "period": payload.period,
                    "model": payload.model,
                    "as_of_date": payload.as_of_date,
                    "generated_at": payload.generated_at,
                    "source_name": payload.source_name,
                    "summary": payload.summary,
                    "total_count": payload.total_count,
                    "rows": payload.rows,
                    "weekly_rankings_total_count": payload.weekly_rankings_total_count,
                    "weekly_rankings": payload.weekly_rankings,
                    "actual_live_performance": payload.actual_live_performance,
                    "errors": payload.errors,
                }
            ),
            200,
        )

    @app.get("/new-entries")
    def new_entries() -> Response:
        require_ops_viewer_access()
        selected_scope = _normalize_admin_new_entries_scope(request.args.get("scope"))
        selected_event_type = _normalize_admin_new_entries_event_type(
            selected_scope,
            request.args.get("event_type"),
        )
        selected_period = _normalize_admin_new_entries_period(request.args.get("period"))
        selected_model = _normalize_admin_new_entries_model(
            selected_scope,
            request.args.get("model"),
        )
        payload = admin_new_entries_api.get_payload(
            scope=selected_scope,
            event_type=selected_event_type,
            period=selected_period,
            model=selected_model,
            force_refresh=request.args.get("refresh") == "1",
        )
        return Response(
            render_template(
                "new_entries.html",
                page_title="신규 편입 추적",
                payload=payload,
                selected_scope=selected_scope,
                selected_event_type=selected_event_type,
                selected_period=selected_period,
                selected_model=selected_model,
                scope_options=[
                    {"value": "user", "label": "사용자용"},
                    {"value": "internal", "label": "내부용"},
                    {"value": "tseries", "label": "T-series"},
                ],
                event_type_options=[
                    {"value": "new_entry", "label": "신규 편입"},
                    {"value": "re_entry", "label": "재편입"},
                    {"value": "new_or_re_entry", "label": "신규 편입+재편입"},
                    {"value": "promotion", "label": "승격"},
                    {"value": "weight_increase", "label": "비중 증가"},
                ],
                period_options=[
                    {"value": "4w", "label": "최근 4주"},
                    {"value": "8w", "label": "최근 8주"},
                    {"value": "all", "label": "전체"},
                ],
                model_options_by_scope={
                    "user": [
                        {"value": "", "label": "전체"},
                        *[
                            {"value": code, "label": USER_MODEL_LABELS.get(code, code)}
                            for code in USER_SCOPE_MODELS
                        ],
                    ],
                    "internal": [
                        {"value": "", "label": "전체"},
                        *[{"value": code, "label": code} for code in INTERNAL_SCOPE_MODELS],
                    ],
                    "tseries": [
                        {"value": "", "label": "전체"},
                        *[{"value": code, "label": code} for code in TSERIES_SCOPE_MODELS],
                    ],
                },
                model_options=(
                    [{"value": "", "label": "전체"}]
                    + (
                        [
                            {"value": code, "label": USER_MODEL_LABELS.get(code, code)}
                            for code in USER_SCOPE_MODELS
                        ]
                        if selected_scope == "user"
                        else (
                            [{"value": code, "label": code} for code in INTERNAL_SCOPE_MODELS]
                            if selected_scope == "internal"
                            else [{"value": code, "label": code} for code in TSERIES_SCOPE_MODELS]
                        )
                    )
                ),
                notice_blocks=_build_notice_blocks("service_nature", "non_advice", "risk"),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/feedback")
    def admin_feedback() -> Response:
        access_context = require_admin_access()
        feedback_rows = safe_list_recent_feedback(limit=100)
        metrics_summary = safe_metrics_summary()
        return Response(
            render_template(
                "admin/feedback.html",
                page_title="Admin Feedback",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                feedback_rows=feedback_rows,
                metrics_summary=metrics_summary,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/metrics")
    def admin_metrics() -> Response:
        access_context = require_admin_access()
        return Response(
            render_template(
                "admin/metrics.html",
                page_title="Admin Metrics",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                metrics_summary=safe_metrics_summary(),
                dashboard_summary=access_store.get_dashboard_summary(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/audit")
    def admin_audit() -> Response:
        access_context = require_admin_access()
        return Response(
            render_template(
                "admin/audit.html",
                page_title="Admin Audit",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                audit_rows=access_store.list_recent_audit_logs(limit=200),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/billing")
    def admin_billing() -> Response:
        access_context = require_admin_access()
        ensure_billing_enabled()
        return Response(
            render_template(
                "admin/billing.html",
                page_title="Admin Billing",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_context),
                order_rows=access_store.list_recent_orders(limit=100),
                payment_event_rows=access_store.list_recent_payment_events(limit=100),
                subscription_rows=access_store.list_recent_subscriptions(limit=100),
            ),
            mimetype="text/html",
        )

    register_status_routes(
        app,
        settings=settings,
        user_snapshot_api=user_snapshot_api,
        market_analysis_api=market_analysis_api,
        maybe_alert_status=maybe_alert_status,
        safe_metrics_summary=safe_metrics_summary,
    )

    return app


if __name__ == "__main__":
    app = create_app()
    current_settings = app.config["SETTINGS"]
    app.run(host=current_settings.web_host, port=current_settings.web_port)
