from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

USER_SCOPE_MODELS = ("stable", "balanced", "growth")
INTERNAL_SCOPE_MODELS = (
    "S2",
    "S3",
    "S3_CORE2",
    "S3_ACCEL_V01",
    "S4",
    "S5",
    "S6",
)
RETIRED_INTERNAL_SCOPE_MODELS = frozenset(
    {
        "S2_PIT_V01",
        "I-STOCK-STRONG-RSI-V01",
    }
)
TSERIES_SCOPE_MODELS = ("T-STOCK-V01", "T-ETF-V01")
SCOPE_KEY_MAP = {
    "user": "user_models",
    "internal": "internal_models",
    "tseries": "tseries_models",
}
EVENT_TYPE_OPTIONS_BY_SCOPE = {
    "user": ("new_entry", "re_entry", "new_or_re_entry", "weight_increase"),
    "internal": ("new_entry", "re_entry", "new_or_re_entry", "weight_increase"),
    "tseries": ("new_entry", "re_entry", "new_or_re_entry", "promotion"),
}
DEFAULT_EVENT_TYPE_BY_SCOPE = {
    "user": "new_entry",
    "internal": "new_entry",
    "tseries": "new_entry",
}
PERIOD_DAYS = {"4w": 28, "8w": 56, "all": 0}
ACTUAL_LIVE_HORIZON_LABELS = {
    "current_return": "현재까지",
    "1w": "1W",
    "2w": "2W",
    "1m": "1M",
    "2m": "2M",
    "3m": "3M",
    "6m": "6M",
    "1y": "1Y",
}
DISPLAY_ACTUAL_LIVE_HORIZONS = ("current_return", "1w", "2w", "1m", "2m", "3m")
DEFAULT_ACTUAL_LIVE_HORIZONS = tuple(ACTUAL_LIVE_HORIZON_LABELS)
DEFAULT_TRACKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "admin_new_entry_tracker.json"
)
QUANT_TRACKER_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\admin_new_entry_tracker.json"
)
DEFAULT_USER_CHANGE_HISTORY_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "public_data"
    / "user_current"
    / "user_model_change_history.json"
)
DEFAULT_TSERIES_DISCOVERY_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "public_data"
    / "tseries_discovery"
    / "current"
    / "quantservice_tseries_discovery.json"
)


def _allow_local_fallback(settings: Settings) -> bool:
    raw_value = os.getenv("ADMIN_NEW_ENTRIES_ALLOW_LOCAL_FALLBACK")
    if raw_value is not None:
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    return settings.app_env != "production"


def _safe_parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split("T")[0].split(" ")[0]
    try:
        return date.fromisoformat(text)
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


def _score_display_mode(score_basis: str, score: float | None) -> str:
    basis = str(score_basis or "").strip().lower()
    if basis in {"i_raw_score", "raw_score", "display_score"}:
        return "number"
    if score is not None and abs(score) > 1:
        return "number"
    return "percent"


@dataclass(frozen=True)
class AdminNewEntriesResult:
    scope: str
    event_type: str
    period: str
    model: str
    as_of_date: str
    generated_at: str
    source_name: str
    summary: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    weekly_rankings: list[dict[str, Any]]
    actual_live_performance: dict[str, Any]
    total_count: int
    weekly_rankings_total_count: int
    errors: list[str]


class AdminNewEntriesApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._allow_local_fallback = _allow_local_fallback(settings)
        self._explicit_path = Path(
            os.getenv("ADMIN_NEW_ENTRY_TRACKER_PATH", "").strip() or str(DEFAULT_TRACKER_PATH)
        )
        explicit_url = os.getenv("ADMIN_NEW_ENTRY_TRACKER_URL", "").strip()
        if explicit_url:
            self._explicit_url = explicit_url
        else:
            snapshot_base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_url = (
                f"{snapshot_base_url}/admin/current/admin_new_entry_tracker.json"
                if snapshot_base_url
                else ""
            )

    def get_payload(
        self,
        *,
        scope: str,
        event_type: str | None,
        period: str,
        model: str | None = None,
        force_refresh: bool = False,
    ) -> AdminNewEntriesResult:
        normalized_scope = self._normalize_scope(scope)
        normalized_period = period if period in PERIOD_DAYS else "8w"
        normalized_model = self._normalize_model(normalized_scope, model)
        normalized_event_type = self._normalize_event_type(normalized_scope, event_type)
        raw_payload, errors = self._load_tracker_payload(force_refresh=force_refresh)
        if not raw_payload and normalized_scope == "user":
            (
                fallback_payload,
                fallback_rows,
                fallback_summary,
            ) = self._load_user_change_history_fallback(
                event_type=normalized_event_type,
                period=normalized_period,
                model=normalized_model,
                force_refresh=force_refresh,
            )
            if fallback_rows:
                errors.append(
                    "admin tracker payload가 없어 user change history fallback을 사용합니다."
                )
                return AdminNewEntriesResult(
                    scope=normalized_scope,
                    event_type=normalized_event_type,
                    period=normalized_period,
                    model=normalized_model,
                    as_of_date=str(fallback_payload.get("as_of_date") or ""),
                    generated_at=str(fallback_payload.get("generated_at") or ""),
                    source_name=str(
                        fallback_payload.get("source_name") or "fallback:user_model_change_history"
                    ),
                    summary=fallback_summary,
                    rows=fallback_rows,
                    weekly_rankings=[],
                    actual_live_performance=self._empty_actual_live_performance(),
                    total_count=len(fallback_rows),
                    weekly_rankings_total_count=0,
                    errors=errors,
                )
        if not raw_payload:
            if normalized_scope == "tseries" and normalized_event_type in {
                "new_entry",
                "re_entry",
                "new_or_re_entry",
            }:
                (
                    rolling_payload,
                    rolling_rows,
                    rolling_summary,
                    rolling_errors,
                ) = self._load_tseries_rolling_event_rows(
                    event_type=normalized_event_type,
                    period=normalized_period,
                    model=normalized_model,
                    force_refresh=force_refresh,
                )
                if rolling_payload:
                    merged_errors = [*errors, *rolling_errors]
                    return AdminNewEntriesResult(
                        scope=normalized_scope,
                        event_type=normalized_event_type,
                        period=normalized_period,
                        model=normalized_model,
                        as_of_date=str(rolling_payload.get("as_of_date") or ""),
                        generated_at=str(rolling_payload.get("generated_at") or ""),
                        source_name=str(rolling_payload.get("source_name") or "tseries_discovery"),
                        summary=rolling_summary,
                        rows=rolling_rows,
                        weekly_rankings=[],
                        actual_live_performance=self._empty_actual_live_performance(),
                        total_count=len(rolling_rows),
                        weekly_rankings_total_count=0,
                        errors=merged_errors,
                    )
            return AdminNewEntriesResult(
                scope=normalized_scope,
                event_type=normalized_event_type,
                period=normalized_period,
                model=normalized_model,
                as_of_date="",
                generated_at="",
                source_name="admin_new_entry_tracker",
                summary=[],
                rows=[],
                weekly_rankings=[],
                actual_live_performance=self._empty_actual_live_performance(),
                total_count=0,
                weekly_rankings_total_count=0,
                errors=errors or ["admin tracker payload unavailable"],
            )
        if str(raw_payload.get("visibility") or "").strip().lower() != "admin_only":
            errors.append("visibility 가 admin_only 가 아닙니다.")

        rows = self._filter_rows(
            raw_payload,
            scope=normalized_scope,
            event_type=normalized_event_type,
            period=normalized_period,
            model=normalized_model,
        )
        summary = self._filter_summary(
            raw_payload,
            scope=normalized_scope,
            event_type=normalized_event_type,
            model=normalized_model,
        )
        weekly_rankings = self._filter_weekly_rankings(
            raw_payload,
            scope=normalized_scope,
            period=normalized_period,
            model=normalized_model,
        )
        actual_live_performance = self._filter_actual_live_performance(raw_payload)
        # NOTE:
        # If admin tracker payload is available, it is the canonical source for
        # admin new-entry pages. Do not silently replace empty tracker results with
        # rolling watchlist rows, because that can reintroduce stale/mismatched
        # data symptoms. Rolling watchlist is used only when tracker load fails.
        return AdminNewEntriesResult(
            scope=normalized_scope,
            event_type=normalized_event_type,
            period=normalized_period,
            model=normalized_model,
            as_of_date=str(raw_payload.get("as_of_date") or ""),
            generated_at=str(raw_payload.get("generated_at") or ""),
            source_name=str(raw_payload.get("source_name") or "admin_new_entry_tracker"),
            summary=summary,
            rows=rows,
            weekly_rankings=weekly_rankings,
            actual_live_performance=actual_live_performance,
            total_count=len(rows),
            weekly_rankings_total_count=len(weekly_rankings),
            errors=errors,
        )

    def _normalize_scope(self, scope: str | None) -> str:
        candidate = str(scope or "").strip().lower()
        return candidate if candidate in SCOPE_KEY_MAP else "user"

    def _normalize_event_type(self, scope: str, event_type: str | None) -> str:
        candidate = str(event_type or "").strip().lower()
        allowed = EVENT_TYPE_OPTIONS_BY_SCOPE.get(scope, ())
        if candidate in allowed:
            return candidate
        return DEFAULT_EVENT_TYPE_BY_SCOPE.get(scope, "new_entry")

    def _event_type_matches(self, selected_event_type: str, row_event_type: str) -> bool:
        normalized_row_event = str(row_event_type or "").strip().lower()
        if selected_event_type == "new_or_re_entry":
            return normalized_row_event in {"new_entry", "re_entry"}
        return normalized_row_event == selected_event_type

    def _is_retired_internal_model(self, model_code: str) -> bool:
        return str(model_code or "").strip().upper() in RETIRED_INTERNAL_SCOPE_MODELS

    def _normalize_model(self, scope: str, model: str | None) -> str:
        candidate = str(model or "").strip()
        if not candidate:
            return ""
        if scope == "user":
            lowered = candidate.lower()
            aliases = {"안정형": "stable", "균형형": "balanced", "성장형": "growth"}
            normalized = aliases.get(candidate, aliases.get(lowered, lowered))
            return normalized if normalized in USER_SCOPE_MODELS else ""
        if scope == "internal":
            uppered = candidate.upper()
            return uppered if uppered in INTERNAL_SCOPE_MODELS else ""
        uppered = candidate.upper()
        if uppered == "T_STOCK_DISCOVERY":
            uppered = "T-STOCK-V01"
        if uppered == "T_ETF_DISCOVERY":
            uppered = "T-ETF-V01"
        return uppered if uppered in TSERIES_SCOPE_MODELS else ""

    def _load_tracker_payload(self, *, force_refresh: bool) -> tuple[dict[str, Any], list[str]]:
        errors: list[str] = []
        if self._explicit_url:
            try:
                request_token = str(int(time.time()))
                request = Request(
                    self._with_cache_buster(self._explicit_url, request_token),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote tracker load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (self._explicit_path, DEFAULT_TRACKER_PATH, QUANT_TRACKER_PATH):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local tracker load failed ({candidate}): {exc}")
        return {}, errors

    def _with_cache_buster(self, url: str, token: str) -> str:
        split = urlsplit(url)
        if split.scheme not in {"http", "https"}:
            return url
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        query["ts"] = token
        return urlunsplit(
            (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
        )

    def _load_user_change_history_fallback(
        self,
        *,
        event_type: str,
        period: str,
        model: str,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        del force_refresh
        payload: dict[str, Any] = {}
        sources: list[Any] = []
        snapshot_base_url = str(self.settings.snapshot_gcs_base_url or "").strip().rstrip("/")
        if snapshot_base_url:
            remote_url = f"{snapshot_base_url}/user_model_change_history.json"
            sources.append(remote_url)
        sources.append(DEFAULT_USER_CHANGE_HISTORY_PATH)

        for source in sources:
            try:
                if isinstance(source, str):
                    request = Request(
                        self._with_cache_buster(source, str(int(time.time()))),
                        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                    )
                    with urlopen(request, timeout=8) as response:
                        payload = json.loads(response.read().decode("utf-8-sig"))
                        break
                else:
                    source_path = Path(source)
                    if source_path.exists():
                        payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
                        break
            except Exception:  # noqa: BLE001
                continue

        if not payload:
            return {}, [], []
        if event_type not in {"new_entry", "new_or_re_entry"}:
            return payload, [], []

        as_of = _safe_parse_date(payload.get("as_of_date"))
        cutoff = None
        period_days = PERIOD_DAYS.get(period, 0)
        if as_of and period_days > 0:
            cutoff = as_of - timedelta(days=period_days)

        weekly_rows: list[dict[str, Any]] = []
        for weekly in payload.get("weekly") or []:
            if not isinstance(weekly, dict):
                continue
            weekly_rows.append(weekly)

        def _weekly_sort_key(row: dict[str, Any]) -> str:
            as_of_text = str(row.get("as_of_date") or row.get("period_key") or "")
            return as_of_text

        weekly_rows.sort(key=_weekly_sort_key)

        first_seen_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for weekly in weekly_rows:
            week_end = str(weekly.get("period_key") or weekly.get("as_of_date") or "-")
            event_day = _safe_parse_date(weekly.get("as_of_date") or weekly.get("period_key"))
            for model_row in weekly.get("models") or []:
                if not isinstance(model_row, dict):
                    continue
                service_profile = str(model_row.get("service_profile") or "").strip().lower()
                model_label = str(model_row.get("user_model_name") or service_profile or "-")
                for item in model_row.get("increase_items") or []:
                    if not isinstance(item, dict):
                        continue
                    ticker = str(item.get("security_code") or "-").strip()
                    if not ticker or ticker == "-":
                        continue
                    key = (service_profile, ticker)
                    if key in first_seen_rows:
                        continue
                    first_seen_rows[key] = {
                        "scope": "user",
                        "model_code": service_profile,
                        "model_label": model_label,
                        "event_type": "new_entry",
                        "event_date": str(weekly.get("as_of_date") or week_end),
                        "week_end": week_end,
                        "first_entry_date": str(weekly.get("as_of_date") or week_end),
                        "ticker": ticker,
                        "name": str(item.get("display_name") or "종목명 미확인"),
                        "delta_weight": _safe_float(item.get("delta_weight")),
                        "curr_weight": None,
                        "current_return": None,
                        "forward_1w": None,
                        "forward_2w": None,
                        "forward_1m": None,
                        "forward_3m": None,
                        "is_current": None,
                    }

        rows: list[dict[str, Any]] = []
        for row in first_seen_rows.values():
            if model and str(row.get("model_code") or "") != model:
                continue
            event_day = _safe_parse_date(row.get("event_date"))
            if cutoff and event_day and event_day < cutoff:
                continue
            rows.append(row)

        rows.sort(
            key=lambda item: (
                str(item.get("event_date") or ""),
                str(item.get("model_code") or ""),
                str(item.get("ticker") or ""),
            ),
            reverse=True,
        )
        summary_map: dict[str, int] = {}
        for row in rows:
            key = f"{row.get('model_code')}|new_entry"
            summary_map[key] = summary_map.get(key, 0) + 1
        summary = [
            {
                "service_profile": key.split("|", maxsplit=1)[0],
                "event_type": "new_entry",
                "count": count,
            }
            for key, count in sorted(summary_map.items())
        ]
        return payload, rows, summary

    def _load_tseries_discovery_payload(
        self, *, force_refresh: bool
    ) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        snapshot_base_url = str(self.settings.snapshot_gcs_base_url or "").strip().rstrip("/")
        sources: list[Any] = []
        if snapshot_base_url:
            sources.append(
                f"{snapshot_base_url}/tseries_discovery/current/quantservice_tseries_discovery.json"
            )
        sources.append(DEFAULT_TSERIES_DISCOVERY_PATH)
        for source in sources:
            try:
                if isinstance(source, str):
                    request = Request(
                        self._with_cache_buster(source, str(int(time.time()))),
                        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                    )
                    with urlopen(request, timeout=8) as response:
                        return json.loads(response.read().decode("utf-8-sig")), errors
                source_path = Path(source)
                if source_path.exists():
                    return json.loads(source_path.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"tseries discovery load failed ({source}): {exc}")
        return {}, errors

    def _load_tseries_rolling_event_rows(
        self,
        *,
        event_type: str,
        period: str,
        model: str,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        payload, errors = self._load_tseries_discovery_payload(force_refresh=force_refresh)
        if not payload:
            return {}, [], [], errors
        as_of = _safe_parse_date(payload.get("as_of_date"))
        cutoff = None
        period_days = PERIOD_DAYS.get(period, 0)
        if as_of and period_days > 0:
            cutoff = as_of - timedelta(days=period_days)

        rows: list[dict[str, Any]] = []
        summary_counter: dict[tuple[str, str], int] = {}

        for model_payload in payload.get("models") or []:
            if not isinstance(model_payload, dict):
                continue
            model_code = str(model_payload.get("model_code") or "").strip().upper()
            if model and model_code != model:
                continue
            event_date_text = str(
                model_payload.get("asof_date") or payload.get("as_of_date") or "-"
            )
            event_day = _safe_parse_date(event_date_text)
            if cutoff and event_day and event_day < cutoff:
                continue
            for item in (model_payload.get("rolling_watchlist") or {}).get("items") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("watch_status") or "").strip().lower() != "new":
                    continue
                appearances_recent = int(item.get("appearances_recent") or 0)
                inferred_event_type = "re_entry" if appearances_recent > 1 else "new_entry"
                if event_type == "new_entry" and inferred_event_type != "new_entry":
                    continue
                if event_type == "re_entry" and inferred_event_type != "re_entry":
                    continue
                if event_type == "new_or_re_entry" and inferred_event_type not in {
                    "new_entry",
                    "re_entry",
                }:
                    continue
                ticker = str(item.get("ticker") or "-").strip() or "-"
                row = {
                    "scope": "tseries",
                    "model_code": model_code,
                    "model_label": model_code,
                    "event_type": inferred_event_type,
                    "event_date": event_date_text,
                    "week_end": event_date_text,
                    "first_entry_date": str(item.get("prev_seen_asof") or event_date_text),
                    "ticker": ticker,
                    "name": str(item.get("name") or "종목명 미확인"),
                    "delta_weight": None,
                    "curr_weight": None,
                    "current_return": None,
                    "forward_1w": None,
                    "forward_2w": None,
                    "forward_1m": None,
                    "forward_3m": None,
                    "is_current": item.get("is_current"),
                }
                rows.append(row)
                counter_key = (model_code, inferred_event_type)
                summary_counter[counter_key] = summary_counter.get(counter_key, 0) + 1

        rows.sort(
            key=lambda item: (
                str(item.get("event_date") or ""),
                str(item.get("model_code") or ""),
                str(item.get("ticker") or ""),
            ),
            reverse=True,
        )
        summary: list[dict[str, Any]] = []
        for (model_code, inferred_event_type), count in sorted(summary_counter.items()):
            summary.append(
                {
                    "model_code": model_code,
                    "event_type": inferred_event_type,
                    "count": count,
                }
            )
        return payload, rows, summary, errors

    def _filter_summary(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
        event_type: str,
        model: str,
    ) -> list[dict[str, Any]]:
        summary_key = SCOPE_KEY_MAP[scope]
        summary_rows = payload.get("summary", {}).get(summary_key) or []
        filtered: list[dict[str, Any]] = []
        for row in summary_rows:
            if not isinstance(row, dict):
                continue
            if not self._event_type_matches(event_type, str(row.get("event_type") or "")):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            if model and row_model != model:
                continue
            filtered.append(dict(row))
        return filtered

    def _filter_rows(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
        event_type: str,
        period: str,
        model: str,
    ) -> list[dict[str, Any]]:
        payload_rows = payload.get(SCOPE_KEY_MAP[scope]) or []
        as_of = _safe_parse_date(payload.get("as_of_date"))
        cutoff = None
        period_days = PERIOD_DAYS.get(period, 0)
        if as_of and period_days > 0:
            cutoff = as_of - timedelta(days=period_days)
        filtered: list[dict[str, Any]] = []
        ranking_lookup = self._build_weekly_ranking_lookup(payload, scope=scope)
        live_start_lookup = self._build_live_start_lookup(payload, scope=scope)
        for row in payload_rows:
            if not isinstance(row, dict):
                continue
            if not self._event_type_matches(event_type, str(row.get("event_type") or "")):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            if model and row_model != model:
                continue
            event_day = _safe_parse_date(row.get("event_date") or row.get("week_end"))
            live_start_day = live_start_lookup.get(row_model)
            if live_start_day and event_day and event_day < live_start_day:
                continue
            if cutoff and event_day and event_day < cutoff:
                continue
            ticker = str(row.get("security_code") or row.get("ticker") or "-").strip() or "-"
            week_end = str(row.get("week_end") or row.get("event_date") or "-")
            ranking = ranking_lookup.get((row_model, ticker, week_end)) or ranking_lookup.get(
                (row_model, ticker, "")
            )
            rank_no = (
                _safe_int(row.get("rank_no"))
                if _safe_int(row.get("rank_no")) is not None
                else (ranking or {}).get("rank_no")
            )
            score = (
                _safe_float(row.get("score"))
                if _safe_float(row.get("score")) is not None
                else (ranking or {}).get("score")
            )
            score_basis = str(row.get("score_basis") or "").strip() or str(
                (ranking or {}).get("score_basis") or ""
            )
            score_weight = (
                _safe_float(row.get("weight"))
                if _safe_float(row.get("weight")) is not None
                else (ranking or {}).get("weight")
            )
            forward_returns = row.get("forward_returns") or {}
            forward_risk_metrics = row.get("forward_risk_metrics") or {}
            current_risk_metrics = row.get("current_risk_metrics") or {}
            one_month_risk = (
                forward_risk_metrics.get("1m")
                if isinstance(forward_risk_metrics.get("1m"), dict)
                else {}
            )
            filtered.append(
                {
                    "scope": scope,
                    "model_code": row_model,
                    "model_label": self._extract_row_model_label(scope, row),
                    "event_type": str(row.get("event_type") or ""),
                    "event_date": str(row.get("event_date") or row.get("week_end") or "-"),
                    "week_end": week_end,
                    "first_entry_date": str(
                        row.get("first_entry_date") or row.get("event_date") or "-"
                    ),
                    "ticker": ticker,
                    "name": str(row.get("display_name") or row.get("name") or "종목명 미확인"),
                    "delta_weight": _safe_float(row.get("delta_weight")),
                    "curr_weight": _safe_float(row.get("curr_weight")),
                    "current_return": _safe_float(row.get("current_return")),
                    "current_mdd": _safe_float(current_risk_metrics.get("mdd")),
                    "current_sharpe": _safe_float(current_risk_metrics.get("sharpe")),
                    "forward_1w": _safe_float(forward_returns.get("1w")),
                    "forward_2w": _safe_float(forward_returns.get("2w")),
                    "forward_1m": _safe_float(forward_returns.get("1m")),
                    "forward_2m": _safe_float(forward_returns.get("2m")),
                    "forward_3m": _safe_float(forward_returns.get("3m")),
                    "forward_6m": _safe_float(forward_returns.get("6m")),
                    "forward_1y": _safe_float(forward_returns.get("1y")),
                    "forward_1m_mdd": _safe_float(one_month_risk.get("mdd")),
                    "forward_1m_sharpe": _safe_float(one_month_risk.get("sharpe")),
                    "is_current": row.get("is_current"),
                    "rank_no": rank_no,
                    "score": score,
                    "score_basis": score_basis,
                    "score_display_mode": _score_display_mode(score_basis, score),
                    "score_weight": score_weight,
                }
            )
        filtered.sort(
            key=lambda item: (
                str(item.get("event_date") or ""),
                str(item.get("model_code") or ""),
                str(item.get("ticker") or ""),
            ),
            reverse=True,
        )
        return filtered

    def _build_weekly_ranking_lookup(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
        ranking_scope_rows = (payload.get("weekly_rankings") or {}).get(SCOPE_KEY_MAP[scope]) or []
        for row in ranking_scope_rows:
            if not isinstance(row, dict):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            ticker = str(row.get("security_code") or row.get("ticker") or "-").strip() or "-"
            week_end = str(row.get("week_end") or row.get("snapshot_date") or "")
            score = _safe_float(row.get("score"))
            score_basis = str(row.get("score_basis") or "").strip()
            normalized = {
                "rank_no": _safe_int(row.get("rank_no")),
                "score": score,
                "score_basis": score_basis,
                "score_display_mode": _score_display_mode(score_basis, score),
                "weight": _safe_float(row.get("weight")),
            }
            lookup[(row_model, ticker, week_end)] = normalized
            lookup.setdefault((row_model, ticker, ""), normalized)
        return lookup

    def _build_live_start_lookup(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
    ) -> dict[str, date]:
        summary = payload.get("actual_live_performance_summary") or {}
        if not isinstance(summary, dict):
            return {}
        lookup: dict[str, date] = {}
        for row in summary.get(SCOPE_KEY_MAP[scope]) or []:
            if not isinstance(row, dict):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            live_start = _safe_parse_date(row.get("live_start_date"))
            if row_model and live_start:
                lookup[row_model] = live_start
        return lookup

    def _build_live_event_performance_lookup(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
        live_start_lookup = self._build_live_start_lookup(payload, scope=scope)
        for row in payload.get(SCOPE_KEY_MAP[scope]) or []:
            if not isinstance(row, dict):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            event_day = _safe_parse_date(row.get("event_date") or row.get("week_end"))
            live_start = live_start_lookup.get(row_model)
            if live_start and event_day and event_day < live_start:
                continue
            ticker = str(row.get("security_code") or row.get("ticker") or "-").strip() or "-"
            week_end = str(row.get("week_end") or row.get("event_date") or "")
            forward_returns = row.get("forward_returns") or {}
            forward_risk_metrics = row.get("forward_risk_metrics") or {}
            current_risk_metrics = row.get("current_risk_metrics") or {}
            one_month_risk = (
                forward_risk_metrics.get("1m")
                if isinstance(forward_risk_metrics.get("1m"), dict)
                else {}
            )
            normalized = {
                "event_type": str(row.get("event_type") or ""),
                "event_date": str(row.get("event_date") or row.get("week_end") or ""),
                "current_return": _safe_float(row.get("current_return")),
                "current_mdd": _safe_float(current_risk_metrics.get("mdd")),
                "current_sharpe": _safe_float(current_risk_metrics.get("sharpe")),
                "forward_1w": _safe_float(forward_returns.get("1w")),
                "forward_2w": _safe_float(forward_returns.get("2w")),
                "forward_1m": _safe_float(forward_returns.get("1m")),
                "forward_2m": _safe_float(forward_returns.get("2m")),
                "forward_3m": _safe_float(forward_returns.get("3m")),
                "forward_1m_mdd": _safe_float(one_month_risk.get("mdd")),
                "forward_1m_sharpe": _safe_float(one_month_risk.get("sharpe")),
            }
            lookup[(row_model, ticker, week_end)] = normalized
            lookup.setdefault((row_model, ticker, ""), normalized)
        return lookup

    def _extract_row_model(self, scope: str, row: dict[str, Any]) -> str:
        if scope == "user":
            return str(row.get("service_profile") or row.get("model_key") or "").strip().lower()
        return str(row.get("model_code") or "").strip().upper()

    def _extract_row_model_label(self, scope: str, row: dict[str, Any]) -> str:
        if scope == "user":
            service_profile = (
                str(row.get("service_profile") or row.get("model_key") or "").strip().lower()
            )
            user_model_name = str(row.get("user_model_name") or "").strip()
            return user_model_name or {
                "stable": "안정형",
                "balanced": "균형형",
                "growth": "성장형",
            }.get(service_profile, service_profile or "-")
        return str(row.get("model_code") or "-")

    def _filter_weekly_rankings(
        self,
        payload: dict[str, Any],
        *,
        scope: str,
        period: str,
        model: str,
    ) -> list[dict[str, Any]]:
        ranking_scope_rows = (payload.get("weekly_rankings") or {}).get(SCOPE_KEY_MAP[scope]) or []
        as_of = _safe_parse_date(payload.get("as_of_date"))
        cutoff = None
        period_days = PERIOD_DAYS.get(period, 0)
        if as_of and period_days > 0:
            cutoff = as_of - timedelta(days=period_days)
        normalized_rows: list[dict[str, Any]] = []
        live_start_lookup = self._build_live_start_lookup(payload, scope=scope)
        event_performance_lookup = self._build_live_event_performance_lookup(payload, scope=scope)
        for row in ranking_scope_rows:
            if not isinstance(row, dict):
                continue
            row_model = self._extract_row_model(scope, row)
            if scope == "internal" and self._is_retired_internal_model(row_model):
                continue
            if model and row_model != model:
                continue
            week_end = str(row.get("week_end") or row.get("snapshot_date") or "-")
            week_end_day = _safe_parse_date(week_end)
            live_start_day = live_start_lookup.get(row_model)
            if live_start_day and week_end_day and week_end_day < live_start_day:
                continue
            if cutoff and week_end_day and week_end_day < cutoff:
                continue
            security_code = str(row.get("security_code") or row.get("ticker") or "-").strip() or "-"
            event_performance = event_performance_lookup.get(
                (row_model, security_code, week_end)
            ) or event_performance_lookup.get((row_model, security_code, ""))
            normalized_rows.append(
                {
                    "scope": scope,
                    "week_end": week_end,
                    "snapshot_date": str(row.get("snapshot_date") or "-"),
                    "model_code": row_model,
                    "model_label": self._extract_row_model_label(scope, row),
                    "service_profile": str(row.get("service_profile") or ""),
                    "user_model_name": str(row.get("user_model_name") or ""),
                    "security_code": security_code,
                    "display_name": str(
                        row.get("display_name") or row.get("name") or "종목명 미확인"
                    ).strip()
                    or "종목명 미확인",
                    "rank_no": _safe_int(row.get("rank_no")),
                    "score": _safe_float(row.get("score")),
                    "score_basis": str(row.get("score_basis") or "-"),
                    "score_display_mode": _score_display_mode(
                        str(row.get("score_basis") or ""), _safe_float(row.get("score"))
                    ),
                    "weight": _safe_float(row.get("weight")),
                    "is_latest_snapshot": row.get("is_latest_snapshot"),
                    "candidate_bucket": str(row.get("candidate_bucket") or ""),
                    "stage1_prob": _safe_float(row.get("stage1_prob")),
                    "stage2_prob": _safe_float(row.get("stage2_prob")),
                    "event_type": (event_performance or {}).get("event_type"),
                    "event_date": (event_performance or {}).get("event_date"),
                    "current_return": (event_performance or {}).get("current_return"),
                    "current_mdd": (event_performance or {}).get("current_mdd"),
                    "current_sharpe": (event_performance or {}).get("current_sharpe"),
                    "forward_1w": (event_performance or {}).get("forward_1w"),
                    "forward_2w": (event_performance or {}).get("forward_2w"),
                    "forward_1m": (event_performance or {}).get("forward_1m"),
                    "forward_2m": (event_performance or {}).get("forward_2m"),
                    "forward_3m": (event_performance or {}).get("forward_3m"),
                    "forward_1m_mdd": (event_performance or {}).get("forward_1m_mdd"),
                    "forward_1m_sharpe": (event_performance or {}).get("forward_1m_sharpe"),
                }
            )
        normalized_rows.sort(
            key=lambda item: (
                str(item.get("week_end") or ""),
                str(item.get("model_code") or ""),
                float(item.get("rank_no") or 999999.0),
                str(item.get("security_code") or ""),
            ),
            reverse=True,
        )
        return normalized_rows

    def _empty_actual_live_performance(self) -> dict[str, Any]:
        return {
            "metric_basis": "",
            "description": "",
            "horizons": [
                {"key": key, "label": label} for key, label in ACTUAL_LIVE_HORIZON_LABELS.items()
            ],
            "rows": [],
            "total_count": 0,
        }

    def _filter_actual_live_performance(
        self,
        payload: dict[str, Any],
        *,
        scope: str | None = None,
        model: str = "",
    ) -> dict[str, Any]:
        summary = payload.get("actual_live_performance_summary") or {}
        if not isinstance(summary, dict):
            return self._empty_actual_live_performance()
        requested_horizons = summary.get("horizons") or DEFAULT_ACTUAL_LIVE_HORIZONS
        allowed_display_horizons = set(DISPLAY_ACTUAL_LIVE_HORIZONS)
        horizon_keys = [
            key
            for key in requested_horizons
            if str(key or "").strip() in ACTUAL_LIVE_HORIZON_LABELS
            and str(key or "").strip() in allowed_display_horizons
        ]
        if not horizon_keys:
            horizon_keys = list(DISPLAY_ACTUAL_LIVE_HORIZONS)

        selected_scopes = (scope,) if scope in SCOPE_KEY_MAP else tuple(SCOPE_KEY_MAP)
        rows: list[dict[str, Any]] = []
        for row_scope in selected_scopes:
            scope_rows = summary.get(SCOPE_KEY_MAP[row_scope]) or []
            for row in scope_rows:
                if not isinstance(row, dict):
                    continue
                row_model = self._extract_row_model(row_scope, row)
                if row_scope == "internal" and self._is_retired_internal_model(row_model):
                    continue
                if model and row_model != model:
                    continue
                metrics = row.get("metrics") or {}
                normalized_metrics: list[dict[str, Any]] = []
                for key in horizon_keys:
                    metric_row = metrics.get(key) or {}
                    if not isinstance(metric_row, dict):
                        metric_row = {}
                    sample_count = _safe_int(metric_row.get("sample_count"))
                    normalized_metrics.append(
                        {
                            "key": key,
                            "label": ACTUAL_LIVE_HORIZON_LABELS[key],
                            "sample_count": sample_count,
                            "avg_return": _safe_float(metric_row.get("avg_return")),
                            "median_return": _safe_float(metric_row.get("median_return")),
                            "win_rate": _safe_float(metric_row.get("win_rate")),
                            "mdd_sample_count": _safe_int(metric_row.get("mdd_sample_count")),
                            "mdd": _safe_float(
                                metric_row.get("avg_mdd")
                                if "avg_mdd" in metric_row
                                else (
                                    metric_row.get("mdd")
                                    if "mdd" in metric_row
                                    else (
                                        metric_row.get("mdd_return")
                                        if "mdd_return" in metric_row
                                        else metric_row.get("max_drawdown")
                                    )
                                )
                            ),
                            "median_mdd": _safe_float(metric_row.get("median_mdd")),
                            "sharpe_sample_count": _safe_int(metric_row.get("sharpe_sample_count")),
                            "sharpe": _safe_float(
                                metric_row.get("avg_sharpe")
                                if "avg_sharpe" in metric_row
                                else (
                                    metric_row.get("sharpe")
                                    if "sharpe" in metric_row
                                    else metric_row.get("sharpe_ratio")
                                )
                            ),
                            "median_sharpe": _safe_float(metric_row.get("median_sharpe")),
                            "has_sample": bool(sample_count and sample_count > 0),
                        }
                    )
                rows.append(
                    {
                        "scope": row_scope,
                        "scope_label": self._scope_label(row_scope),
                        "model_code": row_model,
                        "model_label": self._extract_row_model_label(row_scope, row),
                        "live_start_date": str(row.get("live_start_date") or ""),
                        "source_event_count": _safe_int(row.get("source_event_count")),
                        "live_event_count": _safe_int(row.get("live_event_count")),
                        "latest_live_event_date": str(row.get("latest_live_event_date") or ""),
                        "metric_basis": str(
                            row.get("metric_basis") or summary.get("metric_basis") or ""
                        ),
                        "metrics": normalized_metrics,
                    }
                )
        rows.sort(key=lambda item: str(item.get("model_code") or ""))
        return {
            "metric_basis": str(summary.get("metric_basis") or ""),
            "description": str(summary.get("description") or ""),
            "horizons": [
                {"key": key, "label": ACTUAL_LIVE_HORIZON_LABELS[key]} for key in horizon_keys
            ],
            "rows": rows,
            "total_count": len(rows),
        }

    def _scope_label(self, scope: str) -> str:
        return {
            "user": "사용자용",
            "internal": "내부용",
            "tseries": "T-series",
        }.get(scope, scope)
