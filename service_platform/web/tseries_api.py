from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

T_SERIES_BUCKETS = ("confirmed", "near", "observe")
T_SERIES_WATCH_STATUSES = ("new", "active", "cooling")
T_SERIES_MODEL_REGISTRY = {
    "T-STOCK-V01": {
        "service_model_code": "T_STOCK_DISCOVERY",
        "service_family": "discovery",
        "service_role": "watchlist",
        "display_name_en": "transition-based discovery model",
        "display_name_ko": "전이형 발굴 모델",
        "asset_scope": "stock",
        "display_order": 1,
    },
    "T-ETF-V01": {
        "service_model_code": "T_ETF_DISCOVERY",
        "service_family": "discovery",
        "service_role": "watchlist",
        "display_name_en": "transition-based discovery model",
        "display_name_ko": "전이형 발굴 모델",
        "asset_scope": "etf",
        "display_order": 2,
    },
}
T_SERIES_MODEL_CODE_ALIASES = {model_code: model_code for model_code in T_SERIES_MODEL_REGISTRY} | {
    config["service_model_code"]: model_code
    for model_code, config in T_SERIES_MODEL_REGISTRY.items()
}
T_SERIES_BUCKET_EXPLANATIONS = {
    "confirmed": "우선 검토 후보",
    "near": "다음 순위 후보",
    "observe": "관찰 후보",
}
T_SERIES_DEFAULT_DISCLAIMER_EN = (
    "T-series is a transition-based discovery model. It is designed to identify potential "
    "upgrade candidates, not to replace the existing ranking models."
)
T_SERIES_DEFAULT_DISCLAIMER_KO = (
    "T-series는 전이형 발굴 모델이며, 기존 랭킹형 모델을 대체하기보다 상위 그룹 승격 "
    "가능성이 있는 후보를 탐지하기 위한 모델입니다."
)
T_SERIES_PAYLOAD_FILENAME = "quantservice_tseries_discovery.json"
REMOTE_SOURCES = {"remote", "http", "gcs"}


class TSeriesLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class TSeriesOverview:
    models: list[dict[str, Any]]
    source_name: str
    stale: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TSeriesOperationalApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.local_dir = Path(settings.public_data_dir) / "tseries_discovery" / "current"
        self.cache_ttl_seconds = max(settings.snapshot_cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_overview: TSeriesOverview | None = None
        self._cache_expires_at = 0.0
        self._last_errors: list[str] = []

    def load_overview(self, force_refresh: bool = False) -> TSeriesOverview:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_overview and now < self._cache_expires_at:
                return deepcopy(self._cached_overview)

            try:
                overview = self._load_overview_with_fallbacks()
            except TSeriesLoadError as exc:
                self._last_errors = exc.errors
                if self._cached_overview is not None:
                    fallback = deepcopy(self._cached_overview)
                    fallback.stale = True
                    fallback.warnings = list(fallback.warnings) + [
                        "최신 T-series discovery payload를 읽지 못해 "
                        "마지막 정상 데이터를 표시합니다."
                    ]
                    fallback.errors = exc.errors
                    return fallback
                raise

            self._cached_overview = deepcopy(overview)
            self._cache_expires_at = now + self.cache_ttl_seconds
            self._last_errors = list(overview.errors)
            return overview

    def list_model_summaries(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        overview = self.load_overview(force_refresh=force_refresh)
        return deepcopy([self._build_model_summary(row) for row in overview.models])

    def get_snapshot(self, model_code: str, force_refresh: bool = False) -> dict[str, Any] | None:
        overview = self.load_overview(force_refresh=force_refresh)
        resolved_code = self._resolve_model_code(model_code)
        for row in overview.models:
            if row.get("model_code") == resolved_code:
                return deepcopy(row)
        return None

    def _load_overview_with_fallbacks(self) -> TSeriesOverview:
        errors: list[str] = []
        for loader in self._iter_loaders():
            try:
                overview = loader()
            except TSeriesLoadError as exc:
                errors.extend(exc.errors)
                continue
            if errors:
                overview.warnings = list(overview.warnings) + [
                    "원격 T-series discovery payload를 읽지 못해 로컬 current 데이터를 사용합니다."
                ]
                overview.errors = errors + list(overview.errors)
            return overview
        raise TSeriesLoadError(
            "T-series discovery payload is unavailable.",
            errors=errors,
        )

    def _iter_loaders(self):
        use_remote = self.settings.snapshot_source in REMOTE_SOURCES or bool(
            self.settings.snapshot_gcs_base_url
        )
        if use_remote:
            yield self._load_from_remote_current
        yield self._load_from_local_current

    def _load_from_local_current(self) -> TSeriesOverview:
        local_path = self.local_dir / T_SERIES_PAYLOAD_FILENAME
        if not local_path.exists():
            raise TSeriesLoadError(f"T-series discovery payload does not exist: {local_path}")
        payload = self._read_json(local_path)
        return self._build_overview(payload, f"json:{local_path.name}")

    def _load_from_remote_current(self) -> TSeriesOverview:
        base_url = self._get_remote_base_url().rstrip("/")
        request_token = str(int(time.time()))
        url = self._with_cache_buster(f"{base_url}/{T_SERIES_PAYLOAD_FILENAME}", request_token)
        request_target: str | Request = url
        if urlsplit(url).scheme not in {"file", ""}:
            request_target = Request(
                url,
                headers={
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
        try:
            with urlopen(request_target, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise TSeriesLoadError(f"Failed to load T-series discovery payload: {exc}") from exc
        return self._build_overview(payload, url)

    def _build_overview(self, payload: dict[str, Any], source_name: str) -> TSeriesOverview:
        models = [
            self._normalize_model(row)
            for row in (payload.get("models") or [])
            if isinstance(row, dict)
        ]
        if not models:
            raise TSeriesLoadError(
                "T-series discovery payload is unavailable.",
                errors=[f"T-series discovery payload is unavailable: {source_name}"],
            )
        models.sort(key=lambda row: row.get("meta", {}).get("display_order", 999))
        return TSeriesOverview(
            models=models,
            source_name=str(payload.get("source_name") or source_name),
            warnings=[
                str(item).strip() for item in (payload.get("warnings") or []) if str(item).strip()
            ],
            errors=[
                str(item).strip() for item in (payload.get("errors") or []) if str(item).strip()
            ],
        )

    def _get_remote_base_url(self) -> str:
        base_url = self.settings.snapshot_gcs_base_url.strip().rstrip("/")
        if base_url:
            return base_url + "/tseries_discovery/current"
        raise TSeriesLoadError(
            "Remote T-series discovery source is configured without SNAPSHOT_GCS_BASE_URL."
        )

    @staticmethod
    def _with_cache_buster(url: str, token: str) -> str:
        parts = urlsplit(url)
        if parts.scheme in {"file", ""}:
            return url
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["ts"] = token
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TSeriesLoadError(
                f"Failed to read T-series discovery payload: {path}: {exc}"
            ) from exc

    def _resolve_model_code(self, model_code: str) -> str:
        normalized = str(model_code or "").strip().upper()
        resolved = T_SERIES_MODEL_CODE_ALIASES.get(normalized)
        if not resolved:
            raise TSeriesLoadError(f"Unsupported T-series model: {model_code}")
        return resolved

    def _normalize_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved_code = self._resolve_model_code(str(payload.get("model_code") or ""))
        config = T_SERIES_MODEL_REGISTRY[resolved_code]
        meta_payload = payload.get("meta") or {}
        profile_payload = payload.get("profile") or {}
        run_payload = payload.get("run") or {}
        top_by_bucket_payload = payload.get("top_by_bucket") or {}
        shadow_summary_payload = self._normalize_shadow_summary_payload(
            payload.get("shadow_summary") or {}
        )
        performance_summary_payload = payload.get("performance_summary") or {}
        rolling_watchlist_payload = payload.get("rolling_watchlist") or {}
        bucket_counts_payload = payload.get("bucket_counts") or {}

        top_by_bucket = {
            bucket: [
                self._normalize_candidate(row)
                for row in (top_by_bucket_payload.get(bucket) or [])
                if isinstance(row, dict)
            ][:10]
            for bucket in T_SERIES_BUCKETS
        }
        bucket_counts = {
            bucket: int(
                bucket_counts_payload.get(bucket, len(top_by_bucket.get(bucket) or [])) or 0
            )
            for bucket in T_SERIES_BUCKETS
        }
        shadow_summary = {
            bucket: self._normalize_shadow_row(shadow_summary_payload.get(bucket) or {})
            for bucket in T_SERIES_BUCKETS
            if shadow_summary_payload.get(bucket) is not None
        }
        rolling_watchlist = self._normalize_rolling_watchlist(rolling_watchlist_payload)

        threshold_summary = str(profile_payload.get("threshold_summary") or "").strip()
        if not threshold_summary:
            threshold_summary = self._build_threshold_summary(
                profile_payload.get("threshold_values") or {}
            )

        asset_scope = str(meta_payload.get("asset_scope") or config["asset_scope"]).strip().lower()
        display_name = str(
            meta_payload.get("display_name") or payload.get("display_name") or ""
        ).strip()
        if not display_name:
            display_name = self._public_display_name(resolved_code)

        return {
            "model_code": resolved_code,
            "asof_date": str(
                payload.get("asof_date") or payload.get("latest_asof_date") or "-"
            ).strip()
            or "-",
            "meta": {
                "display_name": display_name,
                "display_name_en": str(
                    meta_payload.get("display_name_en") or config["display_name_en"]
                ).strip(),
                "display_name_ko": str(
                    meta_payload.get("display_name_ko") or config["display_name_ko"]
                ).strip(),
                "service_model_code": str(
                    meta_payload.get("service_model_code") or config["service_model_code"]
                ).strip(),
                "service_family": str(
                    meta_payload.get("service_family") or config["service_family"]
                ).strip(),
                "service_role": str(
                    meta_payload.get("service_role") or config["service_role"]
                ).strip(),
                "asset_scope": asset_scope,
                "version": str(
                    meta_payload.get("version")
                    or meta_payload.get("version_label")
                    or payload.get("version")
                    or "-"
                ).strip()
                or "-",
                "version_label": str(
                    meta_payload.get("version_label")
                    or meta_payload.get("version")
                    or payload.get("version")
                    or "-"
                ).strip()
                or "-",
                "stage_structure": str(meta_payload.get("stage_structure") or "two_stage").strip()
                or "two_stage",
                "status": str(
                    meta_payload.get("status") or payload.get("status") or "active"
                ).strip()
                or "active",
                "notes": str(meta_payload.get("notes") or payload.get("notes") or "").strip(),
                "display_order": int(meta_payload.get("display_order") or config["display_order"]),
                "bucket_explanations": deepcopy(T_SERIES_BUCKET_EXPLANATIONS),
                "disclaimer_en": str(
                    meta_payload.get("disclaimer_en") or T_SERIES_DEFAULT_DISCLAIMER_EN
                ).strip(),
                "disclaimer_ko": str(
                    meta_payload.get("disclaimer_ko") or T_SERIES_DEFAULT_DISCLAIMER_KO
                ).strip(),
            },
            "profile": {
                "profile_code": profile_payload.get("profile_code"),
                "threshold_summary": threshold_summary or "임계값 미공개",
                "risk_filter_version": profile_payload.get("risk_filter_version"),
                "threshold_values": {
                    "stage1_threshold": (profile_payload.get("threshold_values") or {}).get(
                        "stage1_threshold"
                    ),
                    "stage2_confirmed_threshold": (
                        profile_payload.get("threshold_values") or {}
                    ).get("stage2_confirmed_threshold"),
                    "stage2_near_threshold": (profile_payload.get("threshold_values") or {}).get(
                        "stage2_near_threshold"
                    ),
                },
                "notes": profile_payload.get("notes"),
            },
            "run": {
                "refresh_kind": run_payload.get("refresh_kind"),
                "status": run_payload.get("status"),
                "started_at": run_payload.get("started_at"),
                "finished_at": run_payload.get("finished_at"),
                "notes": run_payload.get("notes"),
            },
            "bucket_counts": bucket_counts,
            "top_by_bucket": top_by_bucket,
            "shadow_summary": shadow_summary,
            "rolling_watchlist": rolling_watchlist,
            "performance_summary": self._normalize_performance_summary(performance_summary_payload),
        }

    @staticmethod
    def _normalize_candidate(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "market": row.get("market"),
            "theme_bucket": row.get("theme_bucket"),
            "theme_name_kr": row.get("theme_name_kr"),
            "role_key": row.get("role_key"),
            "role_confidence": row.get("role_confidence"),
            "role_reason": row.get("role_reason"),
            "stage1_prob": row.get("stage1_prob"),
            "stage2_prob": row.get("stage2_prob"),
            "is_s2_overlap": row.get("is_s2_overlap"),
        }

    @staticmethod
    def _normalize_shadow_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "obs_n": row.get("obs_n"),
            "t10_hit_rate": row.get("t10_hit_rate"),
            "t3_hit_rate": row.get("t3_hit_rate"),
            "avg_stage1_prob": row.get("avg_stage1_prob"),
            "avg_stage2_prob": row.get("avg_stage2_prob"),
        }

    @staticmethod
    def _normalize_performance_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "period": row.get("period"),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
            "total_return": row.get("total_return"),
            "cagr": row.get("cagr"),
            "mdd": row.get("mdd"),
            "sharpe": row.get("sharpe"),
        }

    def _normalize_performance_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "headline_metrics": {},
                "period_metrics": [],
                "performance_subject_name": None,
                "performance_subject_type": None,
                "portfolio_generation_basis": None,
            }
        period_metrics = [
            self._normalize_performance_row(row)
            for row in (payload.get("period_metrics") or [])
            if isinstance(row, dict)
        ]
        headline = (
            payload.get("headline_metrics")
            if isinstance(payload.get("headline_metrics"), dict)
            else {}
        )
        return {
            "headline_metrics": {
                "primary_period": headline.get("primary_period"),
                "display_metric": headline.get("display_metric"),
                "cagr": headline.get("cagr"),
                "total_return": headline.get("total_return"),
                "mdd": headline.get("mdd"),
                "sharpe": headline.get("sharpe"),
                "trailing_3m": headline.get("trailing_3m"),
                "trailing_6m": headline.get("trailing_6m"),
                "trailing_1y": headline.get("trailing_1y"),
                "reference_5y": headline.get("reference_5y"),
                "reference_full": headline.get("reference_full"),
                "last_realized_date": headline.get("last_realized_date"),
            },
            "period_metrics": period_metrics,
            "performance_subject_name": payload.get("performance_subject_name"),
            "performance_subject_type": payload.get("performance_subject_type"),
            "portfolio_generation_basis": payload.get("portfolio_generation_basis"),
        }

    @staticmethod
    def _normalize_rolling_watch_item(row: dict[str, Any]) -> dict[str, Any]:
        watch_status = str(row.get("watch_status") or row.get("status") or "").strip().lower()
        watch_tier = str(row.get("watch_tier") or row.get("tier") or "").strip().lower()
        current_bucket = str(row.get("current_bucket") or "").strip().lower() or None
        if current_bucket not in T_SERIES_BUCKETS:
            current_bucket = None

        seen_count_label = "-"
        if row.get("months_seen") is not None:
            seen_count_label = f"{int(row.get('months_seen') or 0)}개월"
        elif row.get("weeks_seen") is not None:
            seen_count_label = f"{int(row.get('weeks_seen') or 0)}주"
        elif row.get("appearances_recent") is not None:
            seen_count_label = f"{int(row.get('appearances_recent') or 0)}회 포착"

        return {
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "market": row.get("market"),
            "theme_bucket": row.get("theme_bucket"),
            "theme_name_kr": row.get("theme_name_kr"),
            "role_key": row.get("role_key"),
            "role_confidence": row.get("role_confidence"),
            "role_reason": row.get("role_reason"),
            "watch_status": watch_status or None,
            "watch_tier": watch_tier or None,
            "is_current": bool(row.get("is_current")),
            "current_bucket": current_bucket,
            "best_bucket_recent": str(row.get("best_bucket_recent") or "").strip().lower() or None,
            "first_seen_date": (
                row.get("first_seen_date")
                or row.get("first_seen_asof")
                or row.get("prev_seen_asof")
            ),
            "last_seen_date": row.get("last_seen_date") or row.get("last_seen_asof"),
            "weeks_seen": row.get("weeks_seen"),
            "months_seen": row.get("months_seen"),
            "appearances_recent": row.get("appearances_recent"),
            "consecutive_current": row.get("consecutive_current"),
            "seen_count_label": seen_count_label,
            "stage1_prob": row.get("stage1_prob"),
            "stage2_prob": row.get("stage2_prob"),
            "is_s2_overlap": row.get("is_s2_overlap"),
        }

    def _normalize_rolling_watchlist(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"enabled": False, "summary_rows": [], "items": []}

        items = [
            self._normalize_rolling_watch_item(row)
            for row in (payload.get("items") or [])
            if isinstance(row, dict)
        ]

        status_counts = {status: 0 for status in T_SERIES_WATCH_STATUSES}
        summary_rows_raw = [row for row in (payload.get("summary") or []) if isinstance(row, dict)]
        for row in summary_rows_raw:
            status = str(row.get("status") or row.get("bucket") or "").strip().lower()
            if status in status_counts:
                try:
                    status_counts[status] = int(row.get("count") or 0)
                except (TypeError, ValueError):
                    status_counts[status] = 0

        if not summary_rows_raw and items:
            for row in items:
                status = row.get("watch_status")
                if status in status_counts:
                    status_counts[status] += 1

        status_order = {status: index for index, status in enumerate(T_SERIES_WATCH_STATUSES)}
        tier_order = {"core": 0, "monitor": 1}
        items.sort(
            key=lambda row: (
                status_order.get(str(row.get("watch_status") or ""), 99),
                tier_order.get(str(row.get("watch_tier") or ""), 99),
                0 if row.get("is_current") else 1,
                str(row.get("name") or ""),
                str(row.get("ticker") or ""),
            )
        )

        return {
            "enabled": bool(summary_rows_raw or items),
            "summary_rows": [
                {"status": status, "count": status_counts.get(status, 0)}
                for status in T_SERIES_WATCH_STATUSES
            ],
            "items": items,
        }

    @staticmethod
    def _normalize_shadow_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            bucket: payload.get(bucket)
            for bucket in T_SERIES_BUCKETS
            if payload.get(bucket) is not None
        }
        if normalized:
            return normalized

        legacy_bucket_map = {
            "historical_stage2": "confirmed",
            "historical_stage1": "near",
        }
        remapped = {
            bucket: payload.get(legacy_key)
            for legacy_key, bucket in legacy_bucket_map.items()
            if payload.get(legacy_key) is not None
        }
        if remapped:
            remapped.setdefault("observe", {})
        return remapped

    @staticmethod
    def _build_threshold_summary(values: dict[str, Any]) -> str:
        parts: list[str] = []
        stage1 = values.get("stage1_threshold")
        confirmed = values.get("stage2_confirmed_threshold")
        near = values.get("stage2_near_threshold")
        if stage1 is not None:
            parts.append(f"1단계 {float(stage1):.3f}")
        if confirmed is not None:
            parts.append(f"우선 후보 {float(confirmed):.3f}")
        if near is not None:
            parts.append(f"근접 후보 {float(near):.3f}")
        return " / ".join(parts) if parts else "임계값 미공개"

    @staticmethod
    def _public_display_name(model_code: str) -> str:
        config = T_SERIES_MODEL_REGISTRY[model_code]
        asset_scope_label = "주식" if config["asset_scope"] == "stock" else "ETF"
        return f"{config['display_name_ko']} · {asset_scope_label}"

    def _build_model_summary(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_code": snapshot["model_code"],
            "service_model_code": snapshot["meta"]["service_model_code"],
            "display_name": snapshot["meta"]["display_name"],
            "display_name_en": snapshot["meta"]["display_name_en"],
            "display_name_ko": snapshot["meta"]["display_name_ko"],
            "asset_scope": snapshot["meta"]["asset_scope"],
            "version": snapshot["meta"]["version"],
            "latest_asof_date": snapshot["asof_date"],
            "profile_code": snapshot["profile"]["profile_code"],
            "threshold_summary": snapshot["profile"]["threshold_summary"],
            "risk_filter_version": snapshot["profile"]["risk_filter_version"],
            "bucket_counts": deepcopy(snapshot["bucket_counts"]),
        }
