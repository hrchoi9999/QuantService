from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

QUANT_ANALYSIS_DB_PATH = Path("D:/QuantAnalysis/analysis.db")
QUANT_ANALYSIS_PORTFOLIO_PATH = Path("D:/QuantAnalysis/outputs/investment_portfolio_latest.json")
DEFAULT_PORTFOLIO_FALLBACK_PATH = (
    Path(__file__).resolve().parent / "admin_data" / "current" / "investment_portfolio_latest.json"
)
MODEL_GROUP_LABELS = {
    "S": "S-series",
    "T": "T-series",
    "I": "I-series",
    "E": "E-series",
}
MODEL_DISPLAY_ALIASES = {
    "I-STOCK-STRONG-RSI-V01": "I-STOCK",
    "T-STOCK-V01": "T-Stock",
    "T-ETF-V01": "T-ETF",
    "E-ETF-V01": "E-ETF",
    "S2_PIT_V01": "S2_PIT",
    "S3_ACCEL_V01": "S3_ACCEL",
}


class InvestmentPortfolioLoadError(RuntimeError):
    """Raised when the investment portfolio payload cannot be loaded."""


@dataclass(frozen=True)
class InvestmentPortfolioBundle:
    source_path: str
    payload: dict[str, Any]
    view: dict[str, Any]


class InvestmentPortfolioApi:
    def __init__(
        self,
        *,
        primary_path: Path = QUANT_ANALYSIS_PORTFOLIO_PATH,
        fallback_path: Path = DEFAULT_PORTFOLIO_FALLBACK_PATH,
        db_path: Path = QUANT_ANALYSIS_DB_PATH,
        settings: Settings | None = None,
    ) -> None:
        self.primary_path = primary_path
        self.fallback_path = fallback_path
        self.db_path = db_path
        self.remote_url = os.getenv("INVESTMENT_PORTFOLIO_URL", "").strip()
        if not self.remote_url and settings and settings.snapshot_gcs_base_url.strip():
            self.remote_url = (
                f"{settings.snapshot_gcs_base_url.rstrip('/')}"
                "/admin/current/investment_portfolio_latest.json"
            )

    def load_bundle(self) -> InvestmentPortfolioBundle:
        payload: dict[str, Any] | None = None
        source_path = ""
        if self.remote_url:
            try:
                payload = self._load_remote_payload()
                source_path = self.remote_url
            except InvestmentPortfolioLoadError:
                payload = None
        if payload is None:
            path = self.primary_path if self.primary_path.exists() else self.fallback_path
            if not path.exists():
                raise InvestmentPortfolioLoadError("investment portfolio payload not found")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InvestmentPortfolioLoadError("investment portfolio payload invalid") from exc
            source_path = str(path)
        if not isinstance(payload, dict):
            raise InvestmentPortfolioLoadError("investment portfolio payload root must be object")
        return InvestmentPortfolioBundle(
            source_path=source_path,
            payload=payload,
            view=_build_view(
                payload,
                source_path,
                _load_portfolio_run_context_from_db(self.db_path),
                _load_step_details_from_db(self.db_path),
                _load_selected_models_from_db(self.db_path),
                _load_stock_candidate_overrides_from_db(self.db_path),
                _load_model_explanation_from_db(self.db_path),
            ),
        )

    def _load_remote_payload(self) -> dict[str, Any]:
        url = _with_cache_buster(self.remote_url)
        request = Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "QuantService/1.0",
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise InvestmentPortfolioLoadError(
                "investment portfolio remote payload invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise InvestmentPortfolioLoadError("investment portfolio payload root must be object")
        return payload


def _with_cache_buster(url: str) -> str:
    split = urlsplit(url)
    if split.scheme not in {"http", "https"}:
        return url
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["_"] = str(int(time.time()))
    return urlunsplit(split._replace(query=urlencode(query)))


def _text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _number(value: Any, decimals: int = 0) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals <= 0:
        return f"{numeric:,.0f}"
    return f"{numeric:,.{decimals}f}"


def _pct_points(value: Any, decimals: int = 2, *, signed: bool = True) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    prefix = "+" if signed and numeric > 0 else ""
    return f"{prefix}{numeric:.{decimals}f}%"


def _build_view(
    payload: dict[str, Any],
    source_path: str,
    db_run_context: dict[str, Any] | None = None,
    db_step_details: list[dict[str, Any]] | None = None,
    selected_models_by_ticker: dict[str, str] | None = None,
    candidate_overrides_by_ticker: dict[str, dict[str, Any]] | None = None,
    db_model_explanation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_risk = payload.get("market_risk") if isinstance(payload.get("market_risk"), dict) else {}
    news_context = (
        payload.get("market_news_context")
        if isinstance(payload.get("market_news_context"), dict)
        else {}
    )
    etf_strategy = (
        payload.get("etf_strategy") if isinstance(payload.get("etf_strategy"), dict) else {}
    )
    stock_strategy = (
        payload.get("stock_strategy") if isinstance(payload.get("stock_strategy"), dict) else {}
    )
    live_data = (
        stock_strategy.get("live_data") if isinstance(stock_strategy.get("live_data"), dict) else {}
    )
    live_status = (
        _text((db_run_context or {}).get("live_data_status"), "")
        or _text(live_data.get("status"), "")
        or "-"
    )
    live_source = (
        _text((db_run_context or {}).get("live_data_source"), "")
        or _text(live_data.get("source"), "")
        or "-"
    )
    live_fetched_at = _text((db_run_context or {}).get("live_fetched_at"), "") or _text(
        live_data.get("fetched_at"), ""
    )
    e_series = (
        etf_strategy.get("e_series_reference")
        if isinstance(etf_strategy.get("e_series_reference"), dict)
        else {}
    )
    step1_v2 = _normalize_step1_v2(market_risk.get("step1_v2"))
    scenario_summary = _normalize_scenario_summary(stock_strategy.get("scenario_summary"))
    validation_scenarios = _normalize_validation_scenarios(
        stock_strategy.get("validation_scenarios")
    )
    return {
        "source_path": source_path,
        "as_of_date": _text(payload.get("as_of_date")),
        "generated_at": _text(payload.get("generated_at")),
        "source_thread": _text(payload.get("source_thread"), "QuantAnalysis"),
        "market_risk": {
            "rating": step1_v2["display_rating"] if step1_v2 else _text(market_risk.get("rating")),
            "direction_label": _text(market_risk.get("direction_label")),
            "total_score": _number(market_risk.get("total_score"), 3),
            "summary": _text(market_risk.get("summary")),
            "action": _text(market_risk.get("action")),
            "is_defensive": "defensive" in _text(market_risk.get("rating"), "").lower(),
            "step1_v2": step1_v2,
        },
        "process_steps": _normalize_steps(payload.get("process_steps")),
        "step_details": db_step_details or _normalize_step_details(payload.get("step_details")),
        "model_explanation": db_model_explanation
        or _normalize_model_explanation(payload.get("model_concentration_explanation")),
        "etf_strategy": {
            "selected_model": _text(etf_strategy.get("selected_model")),
            "reason": _text(etf_strategy.get("reason")),
            "holdings": _normalize_etf_holdings(etf_strategy),
            "e_series": {
                "model_code": _text(e_series.get("strategy_model_code")),
                "as_of_date": _text(e_series.get("as_of_date")),
                "public_allowed": bool(e_series.get("public_recommendation_allowed")),
                "use_policy": _text(e_series.get("use_policy")),
            },
            "portfolio_scenarios": _normalize_portfolio_scenarios(
                etf_strategy.get("portfolio_scenarios")
            ),
            "e_series_scenario_reference": _normalize_e_series_scenario_reference(
                etf_strategy.get("e_series_scenario_reference")
            ),
        },
        "stock_strategy": {
            "exposure_guidance": _text(stock_strategy.get("exposure_guidance")),
            "execution_rule": _text(stock_strategy.get("execution_rule")),
            "live_status": live_status,
            "live_source": live_source,
            "live_fetched_at": live_fetched_at or "-",
            "live_confirmed": live_status in {"ok", "partial", "snapshot_confirmed"},
            "live_not_loaded": live_status == "not_loaded",
            "candidates": _normalize_stock_candidates(
                stock_strategy.get("candidates"),
                selected_models_by_ticker or {},
                candidate_overrides_by_ticker or {},
            ),
            "scenario_summary": scenario_summary,
            "validation_scenarios": validation_scenarios,
        },
        "final_portfolio_strategy": _normalize_final_portfolio_strategy(
            payload.get("final_portfolio_strategy")
        ),
        "risk_headlines": [
            _text(item) for item in (news_context.get("risk_headlines") or []) if _text(item, "")
        ][:6],
        "disclaimer": _text(
            payload.get("disclaimer"),
            "본 자료는 매수/매도 권유가 아닌 참고용 정보입니다.",
        ),
    }


def _load_portfolio_run_context_from_db(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            try:
                refresh_row = connection.execute(
                    """
                    SELECT status, source, fetched_at
                    FROM portfolio_stock_live_refresh_runs
                    ORDER BY refresh_id DESC
                    LIMIT 1
                    """
                ).fetchone()
            except sqlite3.Error:
                refresh_row = None
            if refresh_row is not None:
                return {
                    "live_data_status": refresh_row["status"],
                    "live_data_source": refresh_row["source"],
                    "live_fetched_at": refresh_row["fetched_at"],
                }
            row = connection.execute(
                """
                SELECT live_data_status, live_data_source
                FROM portfolio_runs
                WHERE run_id = (SELECT MAX(run_id) FROM portfolio_runs)
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    return {
        "live_data_status": row["live_data_status"],
        "live_data_source": row["live_data_source"],
    }


def _load_step_details_from_db(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT step_no, title, summary, details_json, conclusion
                FROM portfolio_step_details
                WHERE run_id = (SELECT MAX(run_id) FROM portfolio_runs)
                ORDER BY step_no
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    details: list[dict[str, Any]] = []
    for row in rows:
        details.append(
            {
                "step": _text(row["step_no"]),
                "title": _text(row["title"]),
                "summary": _text(row["summary"]),
                "details": _parse_details_json(row["details_json"]),
                "conclusion": _text(row["conclusion"]),
            }
        )
    return details


def _load_selected_models_from_db(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT ticker, selected_models
                FROM stock_selection_summary
                WHERE selected_models IS NOT NULL
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    result: dict[str, str] = {}
    for row in rows:
        ticker = _text(row["ticker"], "")
        selected_models = _text(row["selected_models"], "")
        if ticker and selected_models:
            result[ticker] = selected_models
    return result


def _load_stock_candidate_overrides_from_db(db_path: Path) -> dict[str, dict[str, Any]]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT ticker, model_display, model_display_codes, model_ids, model_groups,
                       live_price, live_change_pct, foreign_net_억원, institution_net_억원
                FROM portfolio_stock_candidates
                WHERE run_id = (SELECT MAX(run_id) FROM portfolio_runs)
                """
            ).fetchall()
    except sqlite3.Error:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = _text(row["ticker"], "")
        display = _format_stock_candidate_model_display(
            row["model_display"],
            row["model_display_codes"],
            row["model_ids"],
            row["model_groups"],
        )
        if ticker:
            result[ticker] = {
                "model_display": display if display != "-" else None,
                "price": row["live_price"],
                "change_pct": row["live_change_pct"],
                "foreign_net": row["foreign_net_억원"],
                "institution_net": row["institution_net_억원"],
            }
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            live_rows = connection.execute(
                """
                SELECT ticker, model_display, live_price, live_change_pct,
                       foreign_net_억원, institution_net_억원, fetched_at, source
                FROM v_portfolio_stock_live_latest
                """
            ).fetchall()
    except sqlite3.Error:
        live_rows = []
    for row in live_rows:
        ticker = _text(row["ticker"], "")
        if not ticker:
            continue
        current = result.setdefault(ticker, {})
        live_model_display = _text(row["model_display"], "")
        if live_model_display:
            current["model_display"] = live_model_display
        current.update(
            {
                "price": row["live_price"],
                "change_pct": row["live_change_pct"],
                "foreign_net": row["foreign_net_억원"],
                "institution_net": row["institution_net_억원"],
                "fetched_at": row["fetched_at"],
                "source": row["source"],
            }
        )
    return result


def _load_model_explanation_from_db(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT section_title, summary, model_roles_json, why_now_json,
                       interpretation_json, conclusion, generation_method,
                       generation_model, generation_status, narrative_focus
                FROM portfolio_model_explanations
                WHERE run_id = (SELECT MAX(run_id) FROM portfolio_runs)
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    return _normalize_model_explanation(
        {
            "section_title": row["section_title"],
            "summary": row["summary"],
            "model_roles": _parse_json_list(row["model_roles_json"]),
            "why_now": _parse_json_list(row["why_now_json"]),
            "interpretation": _parse_json_list(row["interpretation_json"]),
            "conclusion": row["conclusion"],
            "generation_method": row["generation_method"],
            "generation_model": row["generation_model"],
            "generation_status": row["generation_status"],
            "narrative_focus": row["narrative_focus"],
        }
    )


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _normalize_model_explanation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    generation_method = _text(value.get("generation_method"), "fallback")
    generation_status = _text(value.get("generation_status"), "fallback")
    return {
        "section_title": _text(value.get("section_title"), "모델 분포와 선정 이유"),
        "summary": _text(value.get("summary")),
        "model_roles": _normalize_model_roles(value.get("model_roles")),
        "why_now": [_text(item) for item in value.get("why_now") or [] if _text(item, "")],
        "interpretation": [
            _text(item) for item in value.get("interpretation") or [] if _text(item, "")
        ],
        "conclusion": _text(value.get("conclusion")),
        "generation_method": generation_method,
        "generation_model": _text(value.get("generation_model")),
        "generation_status": generation_status,
        "narrative_focus": _text(value.get("narrative_focus")),
        "is_gemini": generation_method == "gemini" and generation_status == "ok",
    }


def _normalize_model_roles(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "model": _text(item.get("model")),
                "plain_name": _text(item.get("plain_name")),
                "description": _text(item.get("description")),
                "candidate_count": _number(item.get("candidate_count")),
                "candidate_ratio": _pct_points(item.get("candidate_ratio_pct"), signed=False),
            }
        )
    return rows


def _parse_details_json(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item, "")]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return [_text(value)]
    if isinstance(parsed, list):
        return [_text(item) for item in parsed if _text(item, "")]
    return []


def _normalize_step1_v2(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    axes = []
    for item in value.get("axes") or []:
        if not isinstance(item, dict):
            continue
        axes.append(
            {
                "axis": _text(item.get("axis")),
                "score": _number(item.get("score"), 1),
                "max_score": _number(item.get("max_score"), 0),
                "score_label": (
                    f"{_number(item.get('score'), 1)}/" f"{_number(item.get('max_score'), 0)}"
                ),
                "reasons": _normalize_text_list(item.get("reasons")),
                "reason_summary": " · ".join(_normalize_text_list(item.get("reasons"))[:2]),
            }
        )
    return {
        "score": _number(value.get("score"), 1),
        "display_rating": _text(value.get("display_rating") or value.get("label")),
        "effective_asof": _text(value.get("effective_asof") or value.get("effective_date")),
        "legacy_rating": _text(value.get("legacy_rating")),
        "is_boundary": bool(value.get("is_boundary")),
        "boundary_reason": _text(value.get("boundary_reason"), ""),
        "boundary_position": _text(value.get("boundary_position"), ""),
        "axes": axes,
    }


def _normalize_portfolio_scenarios(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(_normalize_scenario(item))
    return rows


def _normalize_scenario(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        item = {}
    return {
        "scenario": _text(item.get("scenario")),
        "name": _text(item.get("name") or item.get("scenario_name")),
        "basis": _text(item.get("basis")),
        "etf_policy": _text(item.get("etf_policy")),
        "stock_policy": _text(item.get("stock_policy")),
        "stock_weight_range_pct": _format_weight_range(item.get("stock_weight_range_pct")),
        "cash_or_defensive_weight": _text(item.get("cash_or_defensive_weight")),
        "activation_condition": _text(item.get("activation_condition")),
    }


def _normalize_e_series_scenario_reference(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "scenario": _text(item.get("scenario")),
                "scenario_name": _text(item.get("scenario_name") or item.get("name")),
                "basis": _text(item.get("basis")),
                "model": _text(item.get("e_series_model") or item.get("strategy_model_code")),
                "as_of_date": _text(item.get("e_series_as_of_date") or item.get("as_of_date")),
                "interpretation": _text(item.get("interpretation")),
                "usage": _text(item.get("usage")),
                "public_allowed": bool(item.get("public_recommendation_allowed")),
            }
        )
    return rows


def _normalize_scenario_summary(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        decision_counts = item.get("decision_counts")
        counts = []
        if isinstance(decision_counts, dict):
            counts = [
                {"decision": _text(decision), "count": _number(count)}
                for decision, count in decision_counts.items()
            ]
        rows.append(
            {
                "scenario": _text(item.get("scenario")),
                "scenario_name": _text(item.get("scenario_name") or item.get("name")),
                "basis": _text(item.get("basis")),
                "decision_counts": counts,
                "interpretation": _text(item.get("interpretation")),
            }
        )
    return rows


def _normalize_validation_scenarios(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "scenario": _text(item.get("scenario")),
                "scenario_name": _text(item.get("scenario_name") or item.get("name")),
                "checks": _normalize_text_list(item.get("checks")),
            }
        )
    return rows


def _normalize_final_portfolio_strategy(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "step1_rating": _text(value.get("step1_rating")),
        "step1_score": _number(value.get("step1_score"), 1),
        "default_scenario": _normalize_scenario(value.get("default_scenario") or {}),
        "conditional_scenario": _normalize_scenario(value.get("conditional_scenario") or {}),
        "transition_conditions": _normalize_text_list(value.get("transition_conditions")),
        "conclusion": _text(value.get("conclusion")),
    }


def _normalize_scenario_decisions(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, list):
        return {}
    rows: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        scenario = _text(item.get("scenario"), "").upper()
        if scenario not in {"A", "B"}:
            continue
        rows[scenario] = {
            "scenario_name": _text(item.get("scenario_name") or item.get("name")),
            "decision": _text(item.get("decision")),
            "max_weight_hint": _text(item.get("max_weight_hint")),
            "activation_condition": _text(item.get("activation_condition")),
            "reason": _text(item.get("reason"), ""),
        }
    return rows


def _normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item, "")]


def _format_weight_range(value: Any) -> str:
    text = _text(value, "")
    if not text:
        return "-"
    return text if "%" in text else f"{text}%"


def _normalize_step_details(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "step": _text(item.get("step") or item.get("step_no")),
                "title": _text(item.get("title")),
                "summary": _text(item.get("summary")),
                "details": _parse_details_json(item.get("details") or item.get("details_json")),
                "conclusion": _text(item.get("conclusion")),
            }
        )
    return rows


def _normalize_steps(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "step": _text(item.get("step")),
                "name": _text(item.get("name")),
                "result": _text(item.get("result")),
            }
        )
    return rows


def _normalize_etf_holdings(etf_strategy: dict[str, Any]) -> list[dict[str, str]]:
    allocation = etf_strategy.get("s6_allocation")
    if not isinstance(allocation, dict):
        return []
    holdings = allocation.get("holdings")
    if not isinstance(holdings, list):
        return []
    rows: list[dict[str, str]] = []
    for item in holdings:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "ticker": _text(item.get("ticker")),
                "name": _text(item.get("name")),
                "role": _text(item.get("role")),
                "weight": _pct_points(item.get("weight_pct"), signed=False),
                "rebalance_date": _text(item.get("rebalance_date")),
            }
        )
    return rows


def _normalize_stock_candidates(
    value: Any,
    selected_models_by_ticker: dict[str, str] | None = None,
    candidate_overrides_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        quote = item.get("live_quote") if isinstance(item.get("live_quote"), dict) else {}
        ticker = _text(item.get("ticker"))
        override = (candidate_overrides_by_ticker or {}).get(ticker) or {}
        foreign_net_value = _first_present(
            override.get("foreign_net"), quote.get("foreign_net_억원")
        )
        institution_net_value = _first_present(
            override.get("institution_net"), quote.get("institution_net_억원")
        )
        net_flow_value = _sum_optional_numbers(foreign_net_value, institution_net_value)
        selected_models = (
            item.get("selected_models")
            or item.get("model_codes")
            or (selected_models_by_ticker or {}).get(ticker)
        )
        scenario_decisions = _normalize_scenario_decisions(item.get("scenario_decisions"))
        model_display = override.get("model_display") or _format_stock_candidate_model_display(
            item.get("model_display"),
            item.get("model_display_codes"),
            item.get("model_ids"),
            selected_models,
            item.get("model_groups"),
            item.get("group"),
        )
        rows.append(
            {
                "ticker": ticker,
                "name": _text(item.get("name")),
                "model_names": model_display,
                "decision": _text(item.get("decision")),
                "latest_selection_date": _text(item.get("latest_selection_date")),
                "price": _number(_first_present(override.get("price"), quote.get("price"))),
                "change_pct": _pct_points(
                    _first_present(override.get("change_pct"), quote.get("change_pct"))
                ),
                "flow_status": _format_flow_status(foreign_net_value, institution_net_value),
                "net_flow": _number(net_flow_value, 1),
                "foreign_net": _number(foreign_net_value, 1),
                "institution_net": _number(institution_net_value, 1),
                "summary": _text(item.get("qualitative_summary")),
                "scenario_decisions": scenario_decisions,
                "scenario_a": scenario_decisions.get("A", {}),
                "scenario_b": scenario_decisions.get("B", {}),
            }
        )
    return rows


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _sum_optional_numbers(*values: Any) -> float | None:
    total = 0.0
    has_value = False
    for value in values:
        if value is None:
            continue
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
        has_value = True
    return total if has_value else None


def _format_flow_status(foreign_net: Any, institution_net: Any) -> str:
    foreign = _sum_optional_numbers(foreign_net)
    institution = _sum_optional_numbers(institution_net)
    if foreign is None and institution is None:
        return "-"
    foreign = foreign or 0.0
    institution = institution or 0.0
    net = foreign + institution
    if foreign > 0 and institution > 0:
        return "동반 순매수"
    if foreign < 0 and institution < 0:
        return "동반 순매도"
    if net > 0:
        return "혼합/순매수"
    if net < 0:
        return "혼합/순매도"
    return "중립"


def _format_stock_candidate_model_display(
    model_display: Any,
    model_display_codes: Any = None,
    model_ids: Any = None,
    selected_models: Any = None,
    groups: Any = None,
    fallback: Any = None,
) -> str:
    direct_display = _text(model_display, "")
    if direct_display:
        return direct_display
    display_codes = _split_model_codes(model_display_codes)
    if display_codes:
        return " / ".join(
            MODEL_DISPLAY_ALIASES.get(code.upper(), code) for code in display_codes if code
        )
    model_id_codes = _split_model_codes(model_ids)
    if model_id_codes:
        return " / ".join(
            MODEL_DISPLAY_ALIASES.get(code.upper(), code) for code in model_id_codes if code
        )
    return _format_selected_models(selected_models, groups, fallback)


def _format_selected_models(value: Any, groups: Any = None, fallback: Any = None) -> str:
    model_codes = _split_model_codes(value)
    if model_codes:
        return " / ".join(
            MODEL_DISPLAY_ALIASES.get(code.upper(), code) for code in model_codes if code
        )
    if isinstance(groups, list):
        labels = [
            MODEL_GROUP_LABELS.get(str(item).strip().upper(), str(item).strip())
            for item in groups
            if str(item or "").strip()
        ]
        return ", ".join(labels) if labels else _text(fallback)
    return _text(fallback)


def _split_model_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    return [str(item).strip() for item in raw_values if str(item or "").strip()]
