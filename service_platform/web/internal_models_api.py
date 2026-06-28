from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

INTERNAL_ADMIN_MODEL_CODES = (
    "S2",
    "S3",
    "S3_CORE2",
    "S3_ACCEL_V01",
    "S4",
    "S5",
    "S6",
    "T-STOCK-V01",
    "T-ETF-V01",
    "E-ETF-V01",
)
RETIRED_INTERNAL_MODEL_CODES = frozenset(
    {
        "S2_PIT_V01",
        "I-STOCK-STRONG-RSI-V01",
    }
)

INTERNAL_MODEL_DISPLAY_NAMES = {
    "I-STOCK-STRONG-RSI-V01": "I-series Strong RSI",
    "E-ETF-V01": "E-series ETF Shadow",
}

INTERNAL_MODEL_NOTES = {
    "S2": "품질과 균형을 함께 보며 안정적인 초과수익 후보를 선별하는 내부 주식 모델입니다.",
    "S3": "성장성과 모멘텀을 함께 보며 공격적인 성장 후보를 추적하는 내부 주식 모델입니다.",
    "S3_CORE2": "S3 후보 중 핵심 신호가 강한 종목을 더 엄격하게 추려 점검하는 코어 모델입니다.",
    "S4": "중기 추세와 리스크 조건을 함께 반영해 성장/모멘텀 후보를 보완하는 내부 모델입니다.",
    "S5": "균형형 포트폴리오 보강을 위해 품질, 수급, 추세를 함께 점검하는 내부 모델입니다.",
    "S6": "방어적 안정성과 하방 리스크 관리를 우선하는 내부 안정성 모델입니다.",
    "S2_PIT_V01": (
        "시점오염을 줄인 PIT 기준으로 S2 전략의 실전 적합성을 점검하는 challenger 모델입니다."
    ),
    "S3_ACCEL_V01": (
        "가속 모멘텀과 성장 신호를 결합해 빠른 상승 후보를 검증하는 challenger 모델입니다."
    ),
    "I-STOCK-STRONG-RSI-V01": (
        "강한 RSI와 초기 상승 탄력을 함께 보며 내부 주식 후보를 선제 관찰하는 I-series 모델입니다."
    ),
    "T-STOCK-V01": "상위 그룹 승격 가능성이 있는 주식 후보를 누적 관찰하는 전이형 발굴 모델입니다.",
    "T-ETF-V01": "ETF 후보의 역할과 시장 국면 적합도를 함께 점검하는 전이형 발굴 모델입니다.",
    "E-ETF-V01": (
        "ETF 전용 데이터와 시장국면을 이용해 역할별 ETF sleeve와 "
        "shadow portfolio를 관찰하는 E-series 모델입니다."
    ),
}

DEFAULT_ADMIN_TRACKER_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "admin_new_entry_tracker.json"
)
QUANT_ADMIN_TRACKER_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\admin_new_entry_tracker.json"
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
QUANT_TSERIES_DISCOVERY_PATH = Path(
    r"D:\Quant\service_platform\web\public_data\current\quantservice_tseries_discovery.json"
)
DEFAULT_AI_OVERLAY_SHADOW_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "internal_models_ai_overlay_shadow_current.json"
)
QUANT_AI_OVERLAY_SHADOW_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\internal_models_ai_overlay_shadow_current.json"
)
DEFAULT_E_SERIES_ETF_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "etf_ai_shadow_portfolio_current.json"
)
QUANT_E_SERIES_ETF_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\etf_ai_shadow_portfolio_current.json"
)
DEFAULT_INTERNAL_VALIDATION_CURRENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "internal_model_validation_current.json"
)
QUANT_INTERNAL_VALIDATION_CURRENT_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\internal_model_validation_current.json"
)
DEFAULT_INTERNAL_VALIDATION_HISTORY_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_platform"
    / "web"
    / "admin_data"
    / "current"
    / "internal_model_validation_history.json"
)
QUANT_INTERNAL_VALIDATION_HISTORY_PATH = Path(
    r"D:\Quant\service_platform\web\admin_data\current\internal_model_validation_history.json"
)


def _allow_local_fallback(settings: Settings) -> bool:
    raw_value = os.getenv("INTERNAL_MODELS_ALLOW_LOCAL_FALLBACK")
    if raw_value is not None:
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    return settings.app_env != "production"


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


def _normalize_model_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_retired_internal_model(value: Any) -> bool:
    return _normalize_model_code(value) in RETIRED_INTERNAL_MODEL_CODES


def _fmt_period_from_key(period_key: str) -> str:
    mapping = {
        "1w": "1W",
        "2w": "2W",
        "1m": "1M",
        "3m": "3M",
        "6m": "6M",
        "1y": "1Y",
        "itd": "ITD",
    }
    return mapping.get(period_key.lower(), period_key.upper())


def _annualize_return(period_return: float, period_months: int) -> float | None:
    if period_months <= 0:
        return None
    if period_return <= -1:
        return None
    try:
        return (1.0 + period_return) ** (12.0 / float(period_months)) - 1.0
    except (OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class InternalModelsBundle:
    source_name: str
    as_of_date: str
    generated_at: str
    models: list[dict[str, Any]]
    performance_comparison: dict[str, list[dict[str, Any]]]
    ai_overlay_shadow: dict[str, Any]
    validation: dict[str, Any]
    errors: list[str]


class InternalModelsApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._allow_local_fallback = _allow_local_fallback(settings)
        configured_path = os.getenv("ADMIN_NEW_ENTRY_TRACKER_PATH", "").strip()
        self._explicit_path = Path(configured_path or str(DEFAULT_ADMIN_TRACKER_PATH))
        configured_url = os.getenv("ADMIN_NEW_ENTRY_TRACKER_URL", "").strip()
        if configured_url:
            self._explicit_url = configured_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_url = (
                f"{base_url}/admin/current/admin_new_entry_tracker.json" if base_url else ""
            )
        configured_tseries_path = os.getenv("TSERIES_DISCOVERY_PATH", "").strip()
        self._explicit_tseries_path = Path(
            configured_tseries_path or str(DEFAULT_TSERIES_DISCOVERY_PATH)
        )
        configured_tseries_url = os.getenv("TSERIES_DISCOVERY_URL", "").strip()
        if configured_tseries_url:
            self._explicit_tseries_url = configured_tseries_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_tseries_url = (
                f"{base_url}/tseries_discovery/current/quantservice_tseries_discovery.json"
                if base_url
                else ""
            )
        configured_overlay_path = os.getenv("INTERNAL_MODELS_AI_OVERLAY_SHADOW_PATH", "").strip()
        self._explicit_overlay_path = Path(
            configured_overlay_path or str(DEFAULT_AI_OVERLAY_SHADOW_PATH)
        )
        configured_overlay_url = os.getenv("INTERNAL_MODELS_AI_OVERLAY_SHADOW_URL", "").strip()
        if configured_overlay_url:
            self._explicit_overlay_url = configured_overlay_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_overlay_url = (
                f"{base_url}/admin/current/internal_models_ai_overlay_shadow_current.json"
                if base_url
                else ""
            )
        configured_e_series_path = os.getenv("E_SERIES_ETF_SHADOW_PATH", "").strip()
        self._explicit_e_series_path = Path(
            configured_e_series_path or str(DEFAULT_E_SERIES_ETF_PATH)
        )
        configured_e_series_url = os.getenv("E_SERIES_ETF_SHADOW_URL", "").strip()
        if configured_e_series_url:
            self._explicit_e_series_url = configured_e_series_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_e_series_url = (
                f"{base_url}/admin/current/etf_ai_shadow_portfolio_current.json" if base_url else ""
            )
        configured_validation_current_path = os.getenv(
            "INTERNAL_MODEL_VALIDATION_CURRENT_PATH", ""
        ).strip()
        self._explicit_validation_current_path = Path(
            configured_validation_current_path or str(DEFAULT_INTERNAL_VALIDATION_CURRENT_PATH)
        )
        configured_validation_current_url = os.getenv(
            "INTERNAL_MODEL_VALIDATION_CURRENT_URL", ""
        ).strip()
        if configured_validation_current_url:
            self._explicit_validation_current_url = configured_validation_current_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_validation_current_url = (
                f"{base_url}/admin/current/internal_model_validation_current.json"
                if base_url
                else ""
            )
        configured_validation_history_path = os.getenv(
            "INTERNAL_MODEL_VALIDATION_HISTORY_PATH", ""
        ).strip()
        self._explicit_validation_history_path = Path(
            configured_validation_history_path or str(DEFAULT_INTERNAL_VALIDATION_HISTORY_PATH)
        )
        configured_validation_history_url = os.getenv(
            "INTERNAL_MODEL_VALIDATION_HISTORY_URL", ""
        ).strip()
        if configured_validation_history_url:
            self._explicit_validation_history_url = configured_validation_history_url
        else:
            base_url = str(settings.snapshot_gcs_base_url or "").strip().rstrip("/")
            self._explicit_validation_history_url = (
                f"{base_url}/admin/current/internal_model_validation_history.json"
                if base_url
                else ""
            )

    def load_bundle(self, *, force_refresh: bool = False) -> InternalModelsBundle:
        payload, errors = self._load_tracker_payload(force_refresh=force_refresh)
        if not payload:
            return InternalModelsBundle(
                source_name="admin_new_entry_tracker",
                as_of_date="",
                generated_at="",
                models=[],
                performance_comparison={"cagr": [], "mdd": [], "sharpe": []},
                ai_overlay_shadow={"enabled": False},
                validation={"enabled": False, "models": []},
                errors=errors or ["admin tracker payload unavailable"],
            )
        overlay_payload, overlay_errors = self._load_ai_overlay_payload(force_refresh=force_refresh)
        errors.extend(overlay_errors)
        overlay_by_model = self._build_ai_overlay_by_model(overlay_payload)
        e_series_payload, e_series_errors = self._load_e_series_payload(force_refresh=force_refresh)
        errors.extend(e_series_errors)
        validation_current, validation_current_errors = self._load_validation_current_payload(
            force_refresh=force_refresh
        )
        errors.extend(validation_current_errors)
        validation_history, validation_history_errors = self._load_validation_history_payload(
            force_refresh=force_refresh
        )
        errors.extend(validation_history_errors)
        models = self._build_model_views(
            payload,
            overlay_by_model=overlay_by_model,
            e_series_payload=e_series_payload,
        )
        return InternalModelsBundle(
            source_name=str(payload.get("source_name") or "admin_new_entry_tracker"),
            as_of_date=str(payload.get("as_of_date") or ""),
            generated_at=str(payload.get("generated_at") or ""),
            models=models,
            performance_comparison=self._build_performance_comparison(models),
            ai_overlay_shadow=self._build_ai_overlay_view(overlay_payload),
            validation=self._build_validation_view(validation_current, validation_history),
            errors=errors,
        )

    def _build_performance_comparison(
        self, models: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        charts: dict[str, list[dict[str, Any]]] = {"cagr": [], "mdd": [], "sharpe": []}
        for model in models:
            performance = model.get("performance") or {}
            label = str(model.get("model_code") or model.get("display_name") or "-")
            for key, source in (
                ("cagr", performance.get("cagr_proxy")),
                ("mdd", performance.get("mdd")),
                ("sharpe", performance.get("sharpe")),
            ):
                value = _safe_float(source)
                if value is None:
                    continue
                score = value if key == "sharpe" else value * 100
                charts[key].append({"label": label, "score": score})
        for key in charts:
            charts[key].sort(key=lambda row: row["score"], reverse=(key != "mdd"))
        return charts

    def _load_tracker_payload(self, *, force_refresh: bool) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        if self._explicit_url:
            try:
                request = Request(
                    self._with_cache_buster(self._explicit_url, str(int(time.time()))),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote tracker load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (
            self._explicit_path,
            DEFAULT_ADMIN_TRACKER_PATH,
            QUANT_ADMIN_TRACKER_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local tracker load failed ({candidate}): {exc}")
        return {}, errors

    def _load_ai_overlay_payload(self, *, force_refresh: bool) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        if self._explicit_overlay_url:
            try:
                request = Request(
                    self._with_cache_buster(self._explicit_overlay_url, str(int(time.time()))),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote ai overlay shadow load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (
            self._explicit_overlay_path,
            DEFAULT_AI_OVERLAY_SHADOW_PATH,
            QUANT_AI_OVERLAY_SHADOW_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local ai overlay shadow load failed ({candidate}): {exc}")
        return {}, errors

    def _load_e_series_payload(self, *, force_refresh: bool) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        if self._explicit_e_series_url:
            try:
                request = Request(
                    self._with_cache_buster(self._explicit_e_series_url, str(int(time.time()))),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote e-series etf load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (
            self._explicit_e_series_path,
            DEFAULT_E_SERIES_ETF_PATH,
            QUANT_E_SERIES_ETF_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local e-series etf load failed ({candidate}): {exc}")
        return {}, errors

    def _load_validation_current_payload(
        self, *, force_refresh: bool
    ) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        if self._explicit_validation_current_url:
            try:
                request = Request(
                    self._with_cache_buster(
                        self._explicit_validation_current_url, str(int(time.time()))
                    ),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote internal validation current load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (
            self._explicit_validation_current_path,
            DEFAULT_INTERNAL_VALIDATION_CURRENT_PATH,
            QUANT_INTERNAL_VALIDATION_CURRENT_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local internal validation current load failed ({candidate}): {exc}")
        return {}, errors

    def _load_validation_history_payload(
        self, *, force_refresh: bool
    ) -> tuple[dict[str, Any], list[str]]:
        del force_refresh
        errors: list[str] = []
        if self._explicit_validation_history_url:
            try:
                request = Request(
                    self._with_cache_buster(
                        self._explicit_validation_history_url, str(int(time.time()))
                    ),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"remote internal validation history load failed: {exc}")
                if not self._allow_local_fallback:
                    return {}, errors
        for candidate in (
            self._explicit_validation_history_path,
            DEFAULT_INTERNAL_VALIDATION_HISTORY_PATH,
            QUANT_INTERNAL_VALIDATION_HISTORY_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig")), errors
            except Exception as exc:  # noqa: BLE001
                errors.append(f"local internal validation history load failed ({candidate}): {exc}")
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

    def _build_model_views(
        self,
        payload: dict[str, Any],
        *,
        overlay_by_model: dict[str, dict[str, Any]] | None = None,
        e_series_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        overlay_by_model = overlay_by_model or {}
        e_series_payload = e_series_payload or {}
        internal_rows = [
            row
            for row in payload.get("internal_models") or []
            if isinstance(row, dict) and not _is_retired_internal_model(row.get("model_code"))
        ]
        tseries_rows = payload.get("tseries_models") or []
        internal_rankings = [
            row
            for row in (payload.get("weekly_rankings") or {}).get("internal_models") or []
            if isinstance(row, dict) and not _is_retired_internal_model(row.get("model_code"))
        ]
        tseries_rankings = (payload.get("weekly_rankings") or {}).get("tseries_models") or []
        performance_summary = payload.get("model_performance_summary") or {}
        internal_performance_rows = [
            row
            for row in performance_summary.get("internal_models") or []
            if isinstance(row, dict) and not _is_retired_internal_model(row.get("model_code"))
        ]
        tseries_performance_rows = performance_summary.get("tseries_models") or []
        perf_by_code: dict[str, dict[str, Any]] = {}
        for row in [*internal_performance_rows, *tseries_performance_rows]:
            if not isinstance(row, dict):
                continue
            code = _normalize_model_code(row.get("model_code"))
            if not code:
                continue
            perf_by_code[code] = row
        tseries_discovery_by_code = self._load_tseries_discovery_performance_map()

        model_codes = list(INTERNAL_ADMIN_MODEL_CODES)
        known_codes = {code.upper() for code in model_codes}
        discovered_codes: set[str] = set()
        for rows in (
            internal_rows,
            tseries_rows,
            internal_rankings,
            tseries_rankings,
            internal_performance_rows,
            tseries_performance_rows,
        ):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = _normalize_model_code(row.get("model_code"))
                if not code or code in known_codes or _is_retired_internal_model(code):
                    continue
                discovered_codes.add(code)
        model_codes.extend(sorted(discovered_codes))

        model_views: list[dict[str, Any]] = []
        for model_code in model_codes:
            if model_code.startswith("T-"):
                scope = "tseries"
                event_rows = [
                    row
                    for row in tseries_rows
                    if isinstance(row, dict)
                    and _normalize_model_code(row.get("model_code")) == model_code
                ]
                ranking_rows = [
                    row
                    for row in tseries_rankings
                    if isinstance(row, dict)
                    and _normalize_model_code(row.get("model_code")) == model_code
                ]
            else:
                scope = "internal"
                event_rows = [
                    row
                    for row in internal_rows
                    if isinstance(row, dict)
                    and _normalize_model_code(row.get("model_code")) == model_code
                ]
                ranking_rows = [
                    row
                    for row in internal_rankings
                    if isinstance(row, dict)
                    and _normalize_model_code(row.get("model_code")) == model_code
                ]
            model_views.append(
                self._build_model_view(
                    scope=scope,
                    model_code=model_code,
                    event_rows=event_rows,
                    ranking_rows=ranking_rows,
                    performance_summary=perf_by_code.get(model_code),
                    tseries_discovery_performance=tseries_discovery_by_code.get(model_code),
                    ai_overlay_shadow=overlay_by_model.get(model_code),
                    e_series_payload=(
                        e_series_payload
                        if model_code
                        == str(e_series_payload.get("model_code") or "").strip().upper()
                        else None
                    ),
                )
            )
        return model_views

    def _build_ai_overlay_by_model(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not payload:
            return {}
        notes_by_model: dict[str, list[str]] = {}
        for note in payload.get("watch_notes") or []:
            if not isinstance(note, dict):
                continue
            model_id = str(note.get("model_id") or "").strip().upper()
            if _is_retired_internal_model(model_id):
                continue
            text = str(note.get("text") or "").strip()
            if model_id and text:
                notes_by_model.setdefault(model_id, []).append(text)
        result: dict[str, dict[str, Any]] = {}
        for row in payload.get("model_summary") or []:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("model_id") or "").strip().upper()
            if not model_id or _is_retired_internal_model(model_id):
                continue
            normalized = self._normalize_ai_overlay_summary_row(row)
            normalized["notes"] = notes_by_model.get(model_id, [])
            result[model_id] = normalized
        return result

    def _build_ai_overlay_view(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {"enabled": False, "family_summary": [], "model_summary": []}
        return {
            "enabled": True,
            "as_of_date": str(payload.get("as_of_date") or ""),
            "generated_at": str(payload.get("generated_at") or ""),
            "status": str(payload.get("status") or ""),
            "live_recommendation_applied": bool(payload.get("live_recommendation_applied")),
            "shadow_tracking_start_date": str(payload.get("shadow_tracking_start_date") or ""),
            "base_data_date": str(payload.get("base_data_date") or ""),
            "interpretation_note": str(payload.get("interpretation_note") or ""),
            "family_summary": [
                self._normalize_ai_overlay_summary_row(row)
                for row in payload.get("family_summary") or []
                if isinstance(row, dict)
            ],
            "model_summary": [
                self._normalize_ai_overlay_summary_row(row)
                for row in payload.get("model_summary") or []
                if isinstance(row, dict)
                and not _is_retired_internal_model(row.get("model_id"))
            ],
        }

    def _normalize_ai_overlay_summary_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": True,
            "strategy_family": str(row.get("strategy_family") or ""),
            "scope_key": str(row.get("scope_key") or ""),
            "model_id": str(row.get("model_id") or ""),
            "policy": str(row.get("policy") or row.get("mapped_policy") or ""),
            "mapped_policy": str(row.get("mapped_policy") or ""),
            "mapped_policy_label_ko": str(row.get("mapped_policy_label_ko") or ""),
            "overlay_result_label_ko": str(row.get("overlay_result_label_ko") or ""),
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
            "notes": [],
        }

    def _build_validation_view(
        self, current_payload: dict[str, Any], history_payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not current_payload:
            return {"enabled": False, "models": [], "history_by_model": {}}
        history_by_model: dict[str, list[dict[str, Any]]] = {}
        for row in history_payload.get("history") or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("model_code") or "").strip().upper()
            if not code:
                continue
            history_by_model.setdefault(code, []).append(
                self._normalize_validation_history_row(row)
            )
        for rows in history_by_model.values():
            rows.sort(key=lambda item: str(item.get("validation_asof_date") or ""), reverse=True)

        models: list[dict[str, Any]] = []
        for row in current_payload.get("models") or []:
            if not isinstance(row, dict):
                continue
            normalized = self._normalize_validation_model(row)
            code = str(normalized.get("model_code") or "").strip().upper()
            if _is_retired_internal_model(code):
                continue
            normalized["history"] = history_by_model.get(code, [])[:8]
            models.append(normalized)

        model_order = {code: index for index, code in enumerate(INTERNAL_ADMIN_MODEL_CODES)}
        models.sort(
            key=lambda item: (
                model_order.get(str(item.get("model_code") or "").strip().upper(), 999),
                str(item.get("model_code") or ""),
            )
        )
        summary = dict(current_payload.get("summary") or {})
        summary["model_count"] = len(models)
        if "active_model_count" in summary:
            summary["active_model_count"] = len(models)
        review_state_counts: dict[str, int] = {}
        for item in models:
            state = str(item.get("review_state") or "unknown")
            review_state_counts[state] = review_state_counts.get(state, 0) + 1
        if review_state_counts:
            summary["by_review_state"] = review_state_counts
        summary["action_required_count"] = sum(
            1
            for item in models
            if str(item.get("review_state") or "").upper() == "ACTION_REQUIRED"
        )

        return {
            "enabled": True,
            "source_name": str(current_payload.get("source_name") or ""),
            "as_of_date": str(current_payload.get("as_of_date") or ""),
            "generated_at": str(current_payload.get("generated_at") or ""),
            "section_title": str(current_payload.get("section_title_ko") or "내부용 모델 검증"),
            "review_schedule": current_payload.get("review_schedule") or {},
            "decision_policy": current_payload.get("decision_policy") or {},
            "metric_definitions": current_payload.get("metric_definitions") or {},
            "summary": summary,
            "models": models,
            "history_summary": history_payload.get("summary") or {},
        }

    def _normalize_validation_model(self, row: dict[str, Any]) -> dict[str, Any]:
        score = row.get("validation_score") or {}
        live = row.get("current_live_metrics") or {}
        backtest = row.get("current_backtest_metrics") or {}
        model_code = str(row.get("model_code") or "").strip().upper()
        return {
            "scope": str(row.get("scope") or ""),
            "model_code": model_code,
            "display_name": INTERNAL_MODEL_DISPLAY_NAMES.get(model_code, model_code),
            "model_note": INTERNAL_MODEL_NOTES.get(
                model_code,
                (
                    "내부 운용 기준으로 live-first 검증 점수와 "
                    "주간 조치 필요 여부를 점검하는 모델입니다."
                ),
            ),
            "model_profile": str(row.get("model_profile") or ""),
            "asof_date": str(row.get("asof_date") or ""),
            "metric_basis": str(row.get("metric_basis") or ""),
            "review_state": str(row.get("review_state") or ""),
            "recommended_action": str(row.get("recommended_action") or ""),
            "review_reasons": [
                str(reason) for reason in row.get("review_reasons") or [] if str(reason).strip()
            ],
            "qualitative_assessment_ko": str(row.get("qualitative_assessment_ko") or ""),
            "total_score": _safe_float(score.get("total_score")),
            "grade": str(score.get("grade") or ""),
            "grade_rule": str(score.get("grade_rule") or ""),
            "score_basis": str(score.get("score_basis") or ""),
            "sample_confidence": str(live.get("sample_confidence") or ""),
            "live": {
                "live_start_date": str(live.get("live_start_date") or ""),
                "live_event_count": _safe_int(live.get("live_event_count")),
                "latest_live_event_date": str(live.get("latest_live_event_date") or ""),
                "current_avg_return": _safe_float(live.get("current_avg_return")),
                "one_month_avg_return": _safe_float(live.get("one_month_avg_return")),
                "one_month_win_rate": _safe_float(live.get("one_month_win_rate")),
                "one_month_avg_mdd": _safe_float(live.get("one_month_avg_mdd")),
                "one_month_sample_count": _safe_int(live.get("one_month_sample_count")),
            },
            "backtest": {
                "trailing_1m": _safe_float(backtest.get("trailing_1m")),
                "trailing_1y": _safe_float(backtest.get("trailing_1y")),
                "cagr": _safe_float(backtest.get("cagr")),
                "mdd_1y": _safe_float(backtest.get("mdd_1y")),
                "sharpe_1y": _safe_float(backtest.get("sharpe_1y")),
                "sample_count": _safe_int(backtest.get("sample_count")),
            },
            "metric_checks": [
                {
                    "metric": str(check.get("metric") or ""),
                    "actual": _safe_float(check.get("actual")),
                    "target": _safe_float(check.get("target")),
                    "pass": bool(check.get("pass")),
                }
                for check in row.get("metric_checks") or []
                if isinstance(check, dict)
            ],
            "history": [],
        }

    def _normalize_validation_history_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "validation_asof_date": str(row.get("validation_asof_date") or ""),
            "model_code": str(row.get("model_code") or ""),
            "display_name": str(row.get("display_name") or row.get("model_code") or ""),
            "review_state": str(row.get("review_state") or ""),
            "recommended_action": str(row.get("recommended_action") or ""),
            "total_score": _safe_float(row.get("total_score")),
            "grade": str(row.get("grade") or ""),
            "sample_confidence": str(row.get("sample_confidence") or ""),
            "live_1m_avg_return": _safe_float(row.get("live_1m_avg_return")),
            "live_1m_win_rate": _safe_float(row.get("live_1m_win_rate")),
            "live_1m_avg_mdd": _safe_float(row.get("live_1m_avg_mdd")),
            "qualitative_assessment_ko": str(row.get("qualitative_assessment_ko") or ""),
        }

    def _load_tseries_discovery_performance_map(self) -> dict[str, dict[str, Any]]:
        payload = self._load_tseries_discovery_payload()
        if not payload:
            return {}
        models = payload.get("models") or []
        result: dict[str, dict[str, Any]] = {}
        for row in models:
            if not isinstance(row, dict):
                continue
            code = str(row.get("model_code") or "").strip().upper()
            if not code:
                continue
            perf = row.get("performance_summary") or {}
            if not isinstance(perf, dict):
                continue
            result[code] = perf
        return result

    def _load_tseries_discovery_payload(self) -> dict[str, Any]:
        if self._explicit_tseries_url:
            try:
                request = Request(
                    self._with_cache_buster(self._explicit_tseries_url, str(int(time.time()))),
                    headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
                )
                with urlopen(request, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8-sig"))
            except Exception:  # noqa: BLE001
                pass
        for candidate in (
            self._explicit_tseries_path,
            DEFAULT_TSERIES_DISCOVERY_PATH,
            QUANT_TSERIES_DISCOVERY_PATH,
        ):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                continue
        return {}

    def _select_e_series_summary(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        primary_variant = str(
            (payload.get("policy") or {}).get("primary_shadow_variant") or ""
        ).strip()
        rows = [row for row in payload.get("backtest_summary") or [] if isinstance(row, dict)]
        if not rows:
            return None
        return next(
            (
                row
                for row in rows
                if primary_variant and str(row.get("variant") or "") == primary_variant
            ),
            rows[0],
        )

    def _build_model_view(
        self,
        *,
        scope: str,
        model_code: str,
        event_rows: list[dict[str, Any]],
        ranking_rows: list[dict[str, Any]],
        performance_summary: dict[str, Any] | None = None,
        tseries_discovery_performance: dict[str, Any] | None = None,
        ai_overlay_shadow: dict[str, Any] | None = None,
        e_series_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = performance_summary or {}
        discovery_summary = tseries_discovery_performance or {}
        e_series_payload = e_series_payload or {}
        latest_week = ""
        if ranking_rows:
            latest_week = max(str(row.get("week_end") or "") for row in ranking_rows)
        latest_holdings = [
            row for row in ranking_rows if str(row.get("week_end") or "") == latest_week
        ]
        latest_holdings.sort(
            key=lambda row: (
                (
                    _safe_int(row.get("rank_no"))
                    if _safe_int(row.get("rank_no")) is not None
                    else 99999
                ),
                str(row.get("security_code") or ""),
            )
        )
        if not latest_holdings and e_series_payload:
            primary_variant = str(
                (e_series_payload.get("policy") or {}).get("primary_shadow_variant") or ""
            ).strip()
            e_holdings = [
                row
                for row in e_series_payload.get("current_holdings") or []
                if isinstance(row, dict)
                and (not primary_variant or str(row.get("variant") or "") == primary_variant)
            ]
            latest_holdings = e_holdings[:30]
            latest_week = str(e_series_payload.get("as_of_date") or "")
        if not latest_holdings:
            # Fallback to latest event rows when ranking rows are not available.
            latest_events = sorted(
                event_rows,
                key=lambda row: str(row.get("event_date") or row.get("week_end") or ""),
                reverse=True,
            )[:25]
            latest_holdings = latest_events
            latest_week = str((latest_events[0].get("event_date") if latest_events else "") or "")

        event_counts: dict[str, int] = {}
        for row in event_rows:
            key = str(row.get("event_type") or "unknown")
            event_counts[key] = event_counts.get(key, 0) + 1

        perf_values = {
            "itd": [],
            "m1": [],
            "m3": [],
            "m6": [],
            "y1": [],
            "mdd": [],
            "sharpe": [],
        }
        for row in event_rows:
            forward = row.get("forward_returns") or {}
            for label, source in (
                ("itd", row.get("current_return")),
                ("m1", forward.get("1m")),
                ("m3", forward.get("3m")),
                ("m6", forward.get("6m")),
                ("y1", forward.get("1y")),
                ("mdd", row.get("mdd")),
                ("sharpe", row.get("sharpe")),
            ):
                value = _safe_float(source)
                if value is not None:
                    perf_values[label].append(value)

        def _avg(label: str) -> float | None:
            values = perf_values[label]
            if not values:
                return None
            return sum(values) / len(values)

        period_metrics: list[dict[str, Any]] = []
        if scope == "tseries" and discovery_summary:
            for row in discovery_summary.get("period_metrics") or []:
                if not isinstance(row, dict):
                    continue
                period_metrics.append(
                    {
                        "period": str(row.get("period") or "-"),
                        "headline_label": "CAGR",
                        "headline_value": _safe_float(row.get("cagr")),
                        "sample_count": _safe_int(summary.get("sample_count")) or 0,
                        "metric_basis": str(
                            discovery_summary.get("performance_subject_type")
                            or discovery_summary.get("portfolio_generation_basis")
                            or "shadow_portfolio"
                        ),
                        "cagr": _safe_float(row.get("cagr")),
                        "mdd": _safe_float(row.get("mdd")),
                        "sharpe": _safe_float(row.get("sharpe")),
                        "total_return": _safe_float(row.get("total_return")),
                    }
                )
        if e_series_payload:
            selected = self._select_e_series_summary(e_series_payload)
            if selected:
                period_metrics.append(
                    {
                        "period": "1M",
                        "headline_label": "평균 1M 수익률",
                        "headline_value": _safe_float(selected.get("avg_1m_ret")),
                        "sample_count": _safe_int(selected.get("observations"))
                        or _safe_int(selected.get("periods"))
                        or 0,
                        "metric_basis": str(selected.get("variant") or "e_series_shadow"),
                        "cagr": None,
                        "mdd": _safe_float(
                            selected.get("avg_1m_mdd") or selected.get("avg_1m_mdd_proxy")
                        ),
                        "sharpe": None,
                        "total_return": _safe_float(selected.get("compounded_validation_return")),
                    }
                )
        summary_period_map = (
            ("1w", "1W", summary.get("trailing_1w")),
            ("2w", "2W", summary.get("trailing_2w")),
            ("1m", "1M", summary.get("trailing_1m")),
            ("3m", "3M", summary.get("trailing_3m")),
            ("6m", "6M", summary.get("trailing_6m")),
            ("1y", "1Y", summary.get("trailing_1y")),
            ("itd", "ITD", summary.get("itd_return")),
        )
        if not period_metrics:
            for _, label, source in summary_period_map:
                value = _safe_float(source)
                if value is None:
                    continue
                period_metrics.append(
                    {
                        "period": label,
                        "headline_label": "수익률",
                        "headline_value": value,
                        "sample_count": _safe_int(summary.get("sample_count")) or 0,
                        "metric_basis": str(summary.get("metric_basis") or ""),
                    }
                )
        if not period_metrics:
            period_keys = ("1w", "2w", "1m", "3m")
            for key in period_keys:
                values: list[float] = []
                for row in event_rows:
                    forward = row.get("forward_returns") or {}
                    value = _safe_float(forward.get(key))
                    if value is not None:
                        values.append(value)
                if values:
                    period_metrics.append(
                        {
                            "period": _fmt_period_from_key(key),
                            "headline_label": "평균 수익률",
                            "headline_value": sum(values) / len(values),
                            "sample_count": len(values),
                        }
                    )
            current_return_values = [
                _safe_float(row.get("current_return"))
                for row in event_rows
                if _safe_float(row.get("current_return")) is not None
            ]
            if current_return_values:
                period_metrics.append(
                    {
                        "period": "ITD",
                        "headline_label": "편입 후 수익률",
                        "headline_value": sum(current_return_values) / len(current_return_values),
                        "sample_count": len(current_return_values),
                    }
                )

        primary_period = next((item for item in period_metrics if item["period"] == "3M"), None)
        if primary_period is None and period_metrics:
            primary_period = period_metrics[0]
        discovery_headline = discovery_summary.get("headline_metrics") or {}
        cagr_proxy = (
            _safe_float(discovery_headline.get("cagr"))
            or _safe_float(summary.get("cagr"))
            or _safe_float(summary.get("cagr_1y"))
            or _avg("y1")
        )
        if cagr_proxy is None and primary_period:
            months = 3 if primary_period["period"] == "3M" else 1
            cagr_proxy = _annualize_return(
                _safe_float(primary_period.get("headline_value")) or 0.0,
                months,
            )

        latest_event_date = ""
        if event_rows:
            latest_event_date = max(
                str(row.get("event_date") or row.get("week_end") or "") for row in event_rows
            )
        latest_event_rows = [
            row
            for row in event_rows
            if str(row.get("event_date") or row.get("week_end") or "") == latest_event_date
        ]
        increase_items: list[dict[str, Any]] = []
        decrease_items: list[dict[str, Any]] = []
        new_reentry_count = 0
        excluded_count = 0
        for row in latest_event_rows:
            delta = _safe_float(row.get("delta_weight"))
            event_type = str(row.get("event_type") or "").strip().lower()
            if event_type in {"new_entry", "re_entry"}:
                new_reentry_count += 1
            if event_type in {
                "exit",
                "excluded",
                "removed",
                "drop",
                "dropout",
                "weight_decrease",
            } or (delta is not None and delta < 0):
                excluded_count += 1
            item = {
                "display_name": str(row.get("display_name") or "종목명 미확인"),
                "security_code": str(row.get("security_code") or ""),
                "delta_weight": delta,
                "event_type": str(row.get("event_type") or "-"),
            }
            if delta is not None:
                if delta >= 0:
                    increase_items.append(item)
                else:
                    decrease_items.append(item)
                continue
            if event_type in {"new_entry", "re_entry", "promotion", "weight_increase"}:
                increase_items.append(item)
            else:
                decrease_items.append(item)

        holdings_view = []
        for row in latest_holdings:
            holdings_view.append(
                {
                    "rank_no": _safe_int(row.get("rank_no")),
                    "display_name": str(
                        row.get("display_name") or row.get("name") or "종목명 미확인"
                    ),
                    "ticker": str(row.get("security_code") or row.get("ticker") or "-"),
                    "weight": _safe_float(
                        row.get("weight") or row.get("curr_weight") or row.get("holding_weight")
                    ),
                    "score": _safe_float(
                        row.get("score")
                        or row.get("e_hybrid_b50_ai50_score")
                        or row.get("sleeve_selection_score")
                    ),
                    "score_basis": str(
                        row.get("score_basis")
                        or (
                            "e_hybrid_b50_ai50_score"
                            if row.get("e_hybrid_b50_ai50_score") is not None
                            else ""
                        )
                        or "-"
                    ),
                    "display_score": _safe_float(
                        row.get("display_score") or row.get("e_quality_score")
                    ),
                    "universe_rank_no": _safe_int(row.get("universe_rank_no")),
                    "universe_rank_score": _safe_float(row.get("universe_rank_score")),
                    "score_display_mode": self._score_display_mode(row),
                    "candidate_bucket": str(row.get("candidate_bucket") or ""),
                    "stage1_prob": _safe_float(row.get("stage1_prob")),
                    "stage2_prob": _safe_float(row.get("stage2_prob")),
                    "snapshot_date": str(
                        row.get("snapshot_date")
                        or row.get("event_date")
                        or row.get("week_end")
                        or "-"
                    ),
                }
            )

        e_selected_summary = (
            self._select_e_series_summary(e_series_payload) if e_series_payload else None
        )
        return {
            "scope": scope,
            "model_code": model_code,
            "display_name": INTERNAL_MODEL_DISPLAY_NAMES.get(model_code, model_code),
            "model_note": INTERNAL_MODEL_NOTES.get(
                model_code,
                "내부 운용 기준으로 편입 후보, 순위, 점수 변화를 함께 점검하는 모델입니다.",
            ),
            "latest_week": latest_week or "-",
            "event_counts": event_counts,
            "event_row_count": len(event_rows),
            "ranking_row_count": len(ranking_rows),
            "holdings": holdings_view[:30],
            "summary_counts": {
                "holding_count": len(holdings_view),
                "new_reentry_count": new_reentry_count,
                "excluded_count": excluded_count,
            },
            "period_view": {
                "primary": primary_period,
                "supporting": period_metrics,
            },
            "change_log": {
                "asof": latest_event_date or "-",
                "increase_items": increase_items[:20],
                "decrease_items": decrease_items[:20],
            },
            "performance": {
                "m1": _safe_float(discovery_headline.get("trailing_1m"))
                or _safe_float(summary.get("trailing_1m"))
                or _avg("m1"),
                "m3": _safe_float(discovery_headline.get("trailing_3m"))
                or _safe_float(summary.get("trailing_3m"))
                or _avg("m3"),
                "m6": _safe_float(discovery_headline.get("trailing_6m"))
                or _safe_float(summary.get("trailing_6m"))
                or _avg("m6"),
                "y1": _safe_float(discovery_headline.get("trailing_1y"))
                or _safe_float(summary.get("trailing_1y"))
                or _avg("y1"),
                "itd": _safe_float(discovery_headline.get("reference_full"))
                or _safe_float(discovery_headline.get("total_return"))
                or _safe_float(summary.get("itd_return"))
                or _avg("itd"),
                "mdd": _safe_float(discovery_headline.get("mdd"))
                or _safe_float(summary.get("mdd_1y"))
                or (
                    _safe_float(
                        e_selected_summary.get("avg_1m_mdd")
                        or e_selected_summary.get("avg_1m_mdd_proxy")
                    )
                    if e_selected_summary
                    else None
                )
                or _avg("mdd"),
                "sharpe": _safe_float(discovery_headline.get("sharpe"))
                or _safe_float(summary.get("sharpe_1y"))
                or _avg("sharpe"),
                "cagr_proxy": cagr_proxy,
            },
            "performance_basis": str(
                discovery_summary.get("performance_subject_type")
                or summary.get("metric_basis")
                or "-"
            ),
            "ai_overlay_shadow": ai_overlay_shadow or {"enabled": False},
        }

    @staticmethod
    def _score_display_mode(row: dict[str, Any]) -> str:
        basis = str(row.get("score_basis") or "").strip().lower()
        score = _safe_float(row.get("score"))
        if basis in {"i_raw_score", "raw_score", "display_score"}:
            return "number"
        if score is not None and abs(score) > 1:
            return "number"
        return "percent"
