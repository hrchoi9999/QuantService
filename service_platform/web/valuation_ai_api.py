from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

ADMIN_CURRENT_FILENAMES = {
    "learning_current": "ai_learning_models_current.json",
    "candidate_validation": "ai_shadow_observation.json",
    "valuation_current": "valuation_ai_challenger_current.json",
    "valuation_performance": "valuation_ai_challenger_shadow_performance.json",
    "valuation_monitor": "valuation_ai_shadow_monitor.json",
    "downside_current": "downside_risk_ai_current.json",
    "downside_tracker": "downside_risk_ai_shadow_tracker.json",
    "theme_persistence": "theme_persistence_ai_current.json",
    "etf_shadow_portfolio": "etf_ai_shadow_portfolio_current.json",
    "overlay_monitor": "ai_learning_overlay_monitor_current.json",
    "e_series_sleeve_selection": "e_series_etf_sleeve_selection_current.json",
    "e_series_sleeve_portfolio": "e_series_etf_sleeve_portfolio_current.json",
    "e_series_policy_hierarchy": "e_series_etf_operational_policy_hierarchy_current.json",
    "e_series_hardening": "e_series_etf_operational_hardening_current.json",
    "e_series_cost_adjusted": "e_series_etf_mode_switch_cost_adjusted_current.json",
    "e_series_turnover_buffer": "e_series_etf_mode_switch_turnover_buffer_current.json",
    "e_series_total_return_adjustment": "e_series_etf_total_return_adjustment_current.json",
}
AI_MODEL_DISPLAY = {
    "AI-CANDIDATE-VALIDATION-V01": {
        "name": "퀀트후보검증AI",
        "role": "후보 검증 그림자 관찰",
    },
    "AI-GROWTH-VALUATION-V01": {
        "name": "주가수준평가AI",
        "role": "평가 참조 도전자 관찰",
    },
    "AI-DOWNSIDE-RISK-V01": {
        "name": "하락위험예측AI",
        "role": "하락 위험 오버레이 관찰",
    },
    "AI-CANDIDATE-RANK-DELTA-V01": {
        "name": "후보순위조정AI",
        "role": "다음 리밸런싱 순위 변화 기반 비중/rank 조정",
    },
    "AI-THEME-PERSISTENCE-V01": {
        "name": "테마지속성AI",
        "role": "테마 지속성 그림자 관찰",
    },
    "AI-ETF-SHADOW-PORTFOLIO-V01": {
        "name": "ETF전용포트폴리오AI",
        "role": "ETF 전용 shadow 포트폴리오 관찰",
    },
    "E-ETF-V01": {
        "name": "ETF전용 E시리즈AI",
        "role": "ETF sleeve와 shadow portfolio를 구성하는 별도 AI 트랙",
    },
    "AI-ETF-ROLE-ALLOCATION-V01": {
        "name": "ETF역할배분AI",
        "role": "시장국면별 ETF 역할 선택",
    },
    "AI-ETF-ROLE-WEIGHT-TEMPLATE-V01": {
        "name": "ETF비중템플릿AI",
        "role": "ETF 역할 포트폴리오 비중 템플릿 선택",
    },
}
DEFAULT_ADMIN_CURRENT_DIR = (
    Path(__file__).resolve().parents[2] / "service_platform" / "web" / "admin_data" / "current"
)
QUANT_ADMIN_CURRENT_DIR = Path(r"D:\Quant\service_platform\web\admin_data\current")


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        return candidate if math.isfinite(candidate) else None
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null", "n/a"}:
        return None
    try:
        candidate = float(text)
    except ValueError:
        return None
    return candidate if math.isfinite(candidate) else None


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
        return int(float(text))
    except ValueError:
        return None


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@dataclass(frozen=True)
class ValuationAiBundle:
    source_name: str
    as_of_date: str
    generated_at: str
    model_code: str
    models: list[dict[str, Any]]
    details: dict[str, dict[str, Any]]
    champion: dict[str, Any]
    challenger: dict[str, Any]
    risk_overlay: dict[str, Any]
    summary_cards: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    performance_summary: list[dict[str, Any]]
    performance_detail: list[dict[str, Any]]
    filter_options: dict[str, list[str]]
    overlay_monitor: dict[str, Any]
    errors: list[str]


class ValuationAiApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
        self._urls = {
            key: os.getenv(f"VALUATION_AI_{key.upper()}_URL", "").strip()
            or (f"{base_url}/admin/current/{filename}" if base_url else "")
            for key, filename in ADMIN_CURRENT_FILENAMES.items()
        }
        self._paths = {
            key: Path(
                os.getenv(f"VALUATION_AI_{key.upper()}_PATH", "").strip()
                or str(DEFAULT_ADMIN_CURRENT_DIR / filename)
            )
            for key, filename in ADMIN_CURRENT_FILENAMES.items()
        }
        self._fallback_paths = {
            key: QUANT_ADMIN_CURRENT_DIR / filename
            for key, filename in ADMIN_CURRENT_FILENAMES.items()
        }

    def load_bundle(
        self,
        *,
        scope: str = "",
        model_code: str = "",
        challenger_state: str = "",
        challenger_change_label: str = "",
        risk_tag: str = "",
        theme_bucket: str = "",
        force_refresh: bool = False,
    ) -> ValuationAiBundle:
        del force_refresh
        payloads: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for key in ADMIN_CURRENT_FILENAMES:
            payload, payload_errors = self._load_payload(key)
            payloads[key] = payload
            errors.extend(payload_errors)

        learning_payload = payloads["learning_current"]
        overlay_monitor = payloads["overlay_monitor"]
        valuation_current = payloads["valuation_current"]
        valuation_performance = payloads["valuation_performance"]
        models = self._normalize_learning_models(
            _as_list(learning_payload.get("models")),
            _as_dict(learning_payload.get("web_display_metadata")),
        )
        models = self._append_etf_component_models(models, payloads["etf_shadow_portfolio"])
        candidates = [
            self._normalize_candidate(row)
            for row in _as_list(valuation_current.get("candidates"))
            if isinstance(row, dict)
        ]
        candidates = self._filter_candidates(
            candidates,
            scope=scope,
            model_code=model_code,
            challenger_state=challenger_state,
            challenger_change_label=challenger_change_label,
            risk_tag=risk_tag,
            theme_bucket=theme_bucket,
        )
        return ValuationAiBundle(
            source_name=_safe_str(learning_payload.get("source_name"))
            or _safe_str(valuation_current.get("source_name"))
            or "ai_learning_models_current",
            as_of_date=_safe_str(learning_payload.get("as_of_date"))
            or _safe_str(valuation_current.get("as_of_date")),
            generated_at=_safe_str(learning_payload.get("generated_at"))
            or _safe_str(valuation_current.get("generated_at")),
            model_code=_safe_str(valuation_current.get("model_code")),
            models=models,
            details={
                "candidate_validation": payloads["candidate_validation"],
                "valuation_ai": {
                    "current": valuation_current,
                    "performance": valuation_performance,
                    "monitor": payloads["valuation_monitor"],
                },
                "downside_risk_ai": {
                    "current": payloads["downside_current"],
                    "tracker": payloads["downside_tracker"],
                },
                "theme_persistence_ai": payloads["theme_persistence"],
                "etf_shadow_portfolio_ai": payloads["etf_shadow_portfolio"],
                "overlay_monitor_ai": overlay_monitor,
                "e_series_etf": {
                    "sleeve_selection": payloads["e_series_sleeve_selection"],
                    "sleeve_portfolio": payloads["e_series_sleeve_portfolio"],
                    "policy_hierarchy": payloads["e_series_policy_hierarchy"],
                    "hardening": payloads["e_series_hardening"],
                    "cost_adjusted": payloads["e_series_cost_adjusted"],
                    "turnover_buffer": payloads["e_series_turnover_buffer"],
                    "total_return_adjustment": payloads["e_series_total_return_adjustment"],
                },
            },
            champion=self._normalize_model_block(valuation_current.get("champion")),
            challenger=self._normalize_model_block(valuation_current.get("challenger")),
            risk_overlay=self._normalize_model_block(valuation_current.get("risk_overlay")),
            summary_cards=[
                row
                for row in _as_list(valuation_current.get("summary_by_model"))
                if isinstance(row, dict)
            ],
            candidates=candidates,
            performance_summary=[
                self._normalize_performance_summary(row)
                for row in _as_list(valuation_performance.get("summary"))
                if isinstance(row, dict)
            ],
            performance_detail=[
                self._normalize_performance_detail(row)
                for row in _as_list(valuation_performance.get("detail"))
                if isinstance(row, dict)
            ][:300],
            filter_options=self._build_filter_options(valuation_current),
            overlay_monitor=self._normalize_overlay_monitor(overlay_monitor),
            errors=errors,
        )

    def _normalize_overlay_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {"enabled": False}
        policy_summary = _as_dict(payload.get("overlay_policy_map_summary"))
        return {
            "enabled": True,
            "as_of_date": _safe_str(payload.get("as_of_date")),
            "generated_at": _safe_str(payload.get("generated_at")),
            "status": _safe_str(payload.get("status")),
            "live_recommendation_applied": bool(payload.get("live_recommendation_applied")),
            "shadow_tracking_start_date": _safe_str(payload.get("shadow_tracking_start_date")),
            "base_data_date": _safe_str(payload.get("base_data_date")),
            "interpretation_note": _safe_str(payload.get("interpretation_note")),
            "null_display_rule": _safe_str(payload.get("null_display_rule")),
            "etf_track_note": _safe_str(payload.get("etf_track_note")),
            "component_models": [
                self._normalize_overlay_component(row)
                for row in _as_list(payload.get("component_models"))
                if isinstance(row, dict)
            ],
            "family_summary": [
                self._normalize_overlay_summary_row(row)
                for row in _as_list(policy_summary.get("family_summary"))
                if isinstance(row, dict)
            ],
            "model_summary": [
                self._normalize_overlay_summary_row(row)
                for row in _as_list(policy_summary.get("model_summary"))
                if isinstance(row, dict)
            ],
        }

    def _normalize_overlay_component(self, row: dict[str, Any]) -> dict[str, Any]:
        model_code = _safe_str(row.get("model_code"))
        display = AI_MODEL_DISPLAY.get(model_code, {})
        return {
            "model_code": model_code,
            "model_name_ko": display.get("name") or _safe_str(row.get("model_name_ko")),
            "role": display.get("role") or _safe_str(row.get("role")),
            "status": _safe_str(row.get("status")) or "shadow_observation",
        }

    def _normalize_overlay_summary_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy_family": _safe_str(row.get("strategy_family")),
            "scope_key": _safe_str(row.get("scope_key")),
            "model_id": _safe_str(row.get("model_id")),
            "policy": _safe_str(row.get("policy") or row.get("mapped_policy")),
            "mapped_policy": _safe_str(row.get("mapped_policy")),
            "mapped_policy_label_ko": _safe_str(row.get("mapped_policy_label_ko")),
            "overlay_result_label_ko": _safe_str(row.get("overlay_result_label_ko")),
            "periods": _safe_int(row.get("periods")),
            "priced_periods": _safe_int(row.get("priced_periods")),
            "baseline_avg_period_return": _safe_float(row.get("baseline_avg_period_return")),
            "avg_period_return": _safe_float(row.get("avg_period_return")),
            "avg_return_delta": _safe_float(row.get("avg_return_delta")),
            "baseline_win_rate": _safe_float(row.get("baseline_win_rate")),
            "win_rate": _safe_float(row.get("win_rate")),
            "win_rate_delta": _safe_float(row.get("win_rate_delta")),
            "baseline_nav_mdd": _safe_float(row.get("baseline_nav_mdd")),
            "nav_mdd": _safe_float(row.get("nav_mdd")),
            "nav_mdd_delta": _safe_float(row.get("nav_mdd_delta")),
        }

    def _load_payload(self, key: str) -> tuple[dict[str, Any], list[str]]:
        remote_errors: list[str] = []
        local_errors: list[str] = []
        url = self._urls.get(key, "")
        if url:
            try:
                request = Request(
                    self._with_cache_buster(url, str(int(time.time()))),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), []
            except Exception as exc:  # noqa: BLE001 - remote current fallback is intentional.
                remote_errors.append(f"{ADMIN_CURRENT_FILENAMES[key]} remote load failed: {exc}")
        for path in (self._paths[key], self._fallback_paths[key]):
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8-sig")), []
            except OSError as exc:
                local_errors.append(f"{ADMIN_CURRENT_FILENAMES[key]} local load failed: {exc}")
            except json.JSONDecodeError as exc:
                local_errors.append(f"{ADMIN_CURRENT_FILENAMES[key]} invalid json: {exc}")
        return {}, remote_errors + local_errors

    def _with_cache_buster(self, url: str, token: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return url
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["ts"] = token
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    def _normalize_learning_models(
        self,
        rows: list[Any],
        web_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalized = []
        web_metadata = web_metadata or {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_code = _safe_str(row.get("model_code"))
            display = AI_MODEL_DISPLAY.get(model_code, {})
            display_metadata = _as_dict(row.get("display_metadata")) or _as_dict(
                web_metadata.get(model_code)
            )
            summary = _as_dict(row.get("summary"))
            normalized.append(
                {
                    "model_code": model_code,
                    "model_name_ko": display_metadata.get("short_name")
                    or display.get("name")
                    or _safe_str(row.get("model_name_ko")),
                    "model_role": display.get("role") or _safe_str(row.get("model_role")),
                    "display_metadata": display_metadata,
                    "status": _safe_str(row.get("status")),
                    "as_of_date": _safe_str(row.get("as_of_date")),
                    "performance_asof_date": _safe_str(row.get("performance_asof_date")),
                    "summary": summary,
                    "payloads": [
                        payload
                        for payload in _as_list(row.get("payloads"))
                        if isinstance(payload, dict)
                    ],
                }
            )
        return normalized

    def _append_etf_component_models(
        self,
        models: list[dict[str, Any]],
        etf_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        existing = {row.get("model_code") for row in models}
        for row in _as_list(etf_payload.get("component_models")):
            if not isinstance(row, dict):
                continue
            model_code = _safe_str(row.get("model_code"))
            if not model_code or model_code in existing:
                continue
            display = AI_MODEL_DISPLAY.get(model_code, {})
            evaluation = _as_dict(row.get("evaluation"))
            models.append(
                {
                    "model_code": model_code,
                    "model_name_ko": display.get("name") or _safe_str(row.get("model_name_ko")),
                    "model_role": display.get("role") or _safe_str(row.get("role")),
                    "display_metadata": {},
                    "status": _safe_str(etf_payload.get("status")) or "shadow_observation",
                    "as_of_date": _safe_str(etf_payload.get("as_of_date")),
                    "performance_asof_date": _safe_str(evaluation.get("current_signal_date")),
                    "summary": evaluation,
                    "payloads": [],
                }
            )
            existing.add(model_code)
        return models

    def _normalize_model_block(self, value: Any) -> dict[str, Any]:
        row = _as_dict(value)
        return {
            "feature_set": _safe_str(row.get("feature_set")),
            "model_version": _safe_str(row.get("model_version")),
            "description": _safe_str(row.get("description")),
            "feature_count": _safe_int(row.get("feature_count")),
            "categorical_count": _safe_int(row.get("categorical_count")),
        }

    def _normalize_candidate(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "scope": _safe_str(row.get("scope")),
            "model_code": _safe_str(row.get("model_code")),
            "security_code": _safe_str(row.get("security_code")),
            "display_name": _safe_str(row.get("display_name")),
            "rank_no": _safe_int(row.get("rank_no")),
            "score": _safe_float(row.get("score")),
            "score_basis": _safe_str(row.get("score_basis")),
            "champion_state": _safe_str(row.get("champion_state")),
            "champion_score": _safe_float(row.get("champion_score")),
            "challenger_state": _safe_str(row.get("challenger_state")),
            "challenger_score": _safe_float(row.get("challenger_score")),
            "challenger_change_label": _safe_str(row.get("challenger_change_label")),
            "risk_tag": _safe_str(row.get("risk_tag")),
            "risk_state": _safe_str(row.get("risk_state")),
            "risk_score": _safe_float(row.get("risk_score")),
            "qm_quantmarket_theme_bucket": _safe_str(row.get("qm_quantmarket_theme_bucket")),
            "qm_theme_momentum_score": _safe_float(row.get("qm_theme_momentum_score")),
            "qm_theme_rotation_score": _safe_float(row.get("qm_theme_rotation_score")),
            "qm_risk_score": _safe_float(row.get("qm_risk_score")),
            "qm_market_stress_score": _safe_float(row.get("qm_market_stress_score")),
        }

    def _normalize_performance_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        sample_count = _safe_int(row.get("sample_count"))
        return {
            "group_type": _safe_str(row.get("group_type")),
            "group_value": _safe_str(row.get("group_value")),
            "horizon": _safe_str(row.get("horizon")),
            "candidate_count": _safe_int(row.get("candidate_count")),
            "sample_count": sample_count,
            "avg_return": _safe_float(row.get("avg_return")) if sample_count else None,
            "median_return": _safe_float(row.get("median_return")) if sample_count else None,
            "win_rate": _safe_float(row.get("win_rate")) if sample_count else None,
            "avg_mdd": _safe_float(row.get("avg_mdd")) if sample_count else None,
            "avg_sharpe": _safe_float(row.get("avg_sharpe")) if sample_count else None,
        }

    def _normalize_performance_detail(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "security_code": _safe_str(row.get("security_code")),
            "display_name": _safe_str(row.get("display_name")),
            "track_start_date": _safe_str(row.get("track_start_date")),
            "champion_state": _safe_str(row.get("champion_state")),
            "challenger_state": _safe_str(row.get("challenger_state")),
            "risk_tag": _safe_str(row.get("risk_tag")),
            "live_current_return": _safe_float(row.get("live_current_return")),
            "live_ret_1w": _safe_float(row.get("live_ret_1w")),
            "live_ret_2w": _safe_float(row.get("live_ret_2w")),
            "live_ret_1m": _safe_float(row.get("live_ret_1m")),
            "live_ret_2m": _safe_float(row.get("live_ret_2m")),
            "live_ret_3m": _safe_float(row.get("live_ret_3m")),
            "live_ret_6m": _safe_float(row.get("live_ret_6m")),
            "live_ret_1y": _safe_float(row.get("live_ret_1y")),
            "live_current_mdd": _safe_float(row.get("live_current_mdd")),
            "live_current_sharpe": _safe_float(row.get("live_current_sharpe")),
        }

    def _filter_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        scope: str,
        model_code: str,
        challenger_state: str,
        challenger_change_label: str,
        risk_tag: str,
        theme_bucket: str,
    ) -> list[dict[str, Any]]:
        filters = {
            "scope": _safe_str(scope),
            "model_code": _safe_str(model_code),
            "challenger_state": _safe_str(challenger_state),
            "challenger_change_label": _safe_str(challenger_change_label),
            "risk_tag": _safe_str(risk_tag),
            "qm_quantmarket_theme_bucket": _safe_str(theme_bucket),
        }
        filtered = candidates
        for key, value in filters.items():
            if value:
                filtered = [row for row in filtered if str(row.get(key) or "") == value]
        return filtered[:500]

    def _build_filter_options(self, payload: dict[str, Any]) -> dict[str, list[str]]:
        rows = [row for row in _as_list(payload.get("candidates")) if isinstance(row, dict)]
        fields = {
            "scope": "scope",
            "model_code": "model_code",
            "challenger_state": "challenger_state",
            "challenger_change_label": "challenger_change_label",
            "risk_tag": "risk_tag",
            "theme_bucket": "qm_quantmarket_theme_bucket",
        }
        return {
            name: sorted({_safe_str(row.get(field)) for row in rows if _safe_str(row.get(field))})
            for name, field in fields.items()
        }
