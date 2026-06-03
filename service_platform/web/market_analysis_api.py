from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from service_platform.shared.config import Settings

MARKET_ANALYSIS_FILES = {
    "home": "quantservice_market_home.json",
    "today": "quantservice_market_today.json",
    "page": "quantservice_market_page.json",
    "manifest": "quantservice_market_manifest.json",
    "timeline": "quantservice_market_timeline.json",
    "asset_strength": "quantservice_market_asset_strength.json",
    "state_transition": "quantservice_market_state_transition.json",
    "model_background": "quantservice_market_model_background.json",
    "timeline_history": "quantservice_market_timeline_history.json",
    "asset_strength_history": "quantservice_market_asset_strength_history.json",
    "state_transition_history": "quantservice_market_state_transition_history.json",
    "next_day_preview": "quantservice_market_next_day_preview.json",
    "next_day_preview_history": "quantservice_market_next_day_preview_history.json",
    "next_day_preview_manifest": "market_next_day_preview_manifest.json",
    "analysis_tabs": "quantservice_market_analysis_tabs.json",
    "live_context": "quantservice_market_live_context.json",
    "data_guide": "quantservice_market_data_guide.json",
    "dart_summary": "quantservice_market_dart_summary.json",
    "dart_summary_history": "quantservice_market_dart_summary_history.json",
    "breadth_detail": "quantservice_market_breadth_detail.json",
    "breadth_detail_history": "quantservice_market_breadth_detail_history.json",
    "us_macro_panel": "quantservice_market_us_macro_panel.json",
    "us_macro_panel_history": "quantservice_market_us_macro_panel_history.json",
    "environment_indicators": "quantservice_market_environment_indicators.json",
    "api_environment_indicators": "api_v1_market_environment_indicators.json",
    "environment_indicators_manifest": "quantservice_market_environment_indicators_manifest.json",
    "api_home": "api_v1_market_analysis_home.json",
    "api_page": "api_v1_market_analysis_page.json",
    "api_summary": "api_v1_market_analysis_summary.json",
    "api_detail": "api_v1_market_analysis_detail.json",
    "api_today_bridge": "api_v1_market_analysis_today_bridge.json",
    "api_timeline": "api_v1_market_analysis_timeline.json",
    "api_asset_strength": "api_v1_market_analysis_asset_strength.json",
    "api_state_transition": "api_v1_market_analysis_state_transition.json",
    "api_model_background": "api_v1_market_analysis_model_background.json",
    "api_next_day_preview": "api_v1_market_analysis_next_day_preview.json",
    "api_analysis_tabs": "api_v1_market_analysis_tabs.json",
    "api_live_context": "api_v1_market_analysis_live_context.json",
    "api_data_guide": "api_v1_market_analysis_data_guide.json",
    "api_dart_summary": "api_v1_market_analysis_dart_summary.json",
    "api_dart_summary_history": "api_v1_market_analysis_dart_summary_history.json",
    "api_breadth_detail": "api_v1_market_analysis_breadth_detail.json",
    "api_breadth_detail_history": "api_v1_market_analysis_breadth_detail_history.json",
    "api_us_macro_panel": "api_v1_market_analysis_us_macro_panel.json",
    "api_us_macro_panel_history": "api_v1_market_analysis_us_macro_panel_history.json",
    "api_timeline_history": "api_v1_market_analysis_timeline_history.json",
    "api_asset_strength_history": "api_v1_market_analysis_asset_strength_history.json",
    "api_state_transition_history": "api_v1_market_analysis_state_transition_history.json",
    "api_next_day_preview_history": "api_v1_market_analysis_next_day_preview_history.json",
}
OPTIONAL_MARKET_ANALYSIS_KEYS = {
    "timeline",
    "asset_strength",
    "state_transition",
    "model_background",
    "timeline_history",
    "asset_strength_history",
    "state_transition_history",
    "next_day_preview_history",
    "api_timeline",
    "api_asset_strength",
    "api_state_transition",
    "api_model_background",
    "next_day_preview",
    "next_day_preview_manifest",
    "analysis_tabs",
    "live_context",
    "data_guide",
    "dart_summary",
    "dart_summary_history",
    "breadth_detail",
    "breadth_detail_history",
    "us_macro_panel",
    "us_macro_panel_history",
    "environment_indicators",
    "api_environment_indicators",
    "environment_indicators_manifest",
    "api_next_day_preview",
    "api_analysis_tabs",
    "api_live_context",
    "api_data_guide",
    "api_dart_summary",
    "api_dart_summary_history",
    "api_breadth_detail",
    "api_breadth_detail_history",
    "api_us_macro_panel",
    "api_us_macro_panel_history",
    "api_timeline_history",
    "api_asset_strength_history",
    "api_state_transition_history",
    "api_next_day_preview_history",
}
REMOTE_SOURCES = {"remote", "http", "gcs"}
HISTORY_MARKET_ANALYSIS_KEYS = {
    "timeline_history",
    "asset_strength_history",
    "state_transition_history",
    "next_day_preview_history",
    "dart_summary_history",
    "breadth_detail_history",
    "us_macro_panel_history",
    "api_timeline_history",
    "api_asset_strength_history",
    "api_state_transition_history",
    "api_next_day_preview_history",
    "api_dart_summary_history",
    "api_breadth_detail_history",
    "api_us_macro_panel_history",
}
STRICT_MARKET_ANALYSIS_ASOF_KEYS = {
    "home",
    "today",
    "page",
    "api_home",
    "api_page",
    "api_summary",
    "api_detail",
    "api_today_bridge",
}


def _normalized_asof(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_asof(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    return _normalized_asof(payload.get("asof") or payload.get("as_of_date"))


class MarketAnalysisLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class MarketAnalysisBundle:
    home: dict[str, Any] = field(default_factory=dict)
    today: dict[str, Any] = field(default_factory=dict)
    page: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    asset_strength: dict[str, Any] = field(default_factory=dict)
    state_transition: dict[str, Any] = field(default_factory=dict)
    model_background: dict[str, Any] = field(default_factory=dict)
    timeline_history: dict[str, Any] = field(default_factory=dict)
    asset_strength_history: dict[str, Any] = field(default_factory=dict)
    state_transition_history: dict[str, Any] = field(default_factory=dict)
    next_day_preview: dict[str, Any] = field(default_factory=dict)
    next_day_preview_history: dict[str, Any] = field(default_factory=dict)
    next_day_preview_manifest: dict[str, Any] = field(default_factory=dict)
    analysis_tabs: dict[str, Any] = field(default_factory=dict)
    live_context: dict[str, Any] = field(default_factory=dict)
    data_guide: dict[str, Any] = field(default_factory=dict)
    dart_summary: dict[str, Any] = field(default_factory=dict)
    dart_summary_history: dict[str, Any] = field(default_factory=dict)
    breadth_detail: dict[str, Any] = field(default_factory=dict)
    breadth_detail_history: dict[str, Any] = field(default_factory=dict)
    us_macro_panel: dict[str, Any] = field(default_factory=dict)
    us_macro_panel_history: dict[str, Any] = field(default_factory=dict)
    environment_indicators: dict[str, Any] = field(default_factory=dict)
    api_environment_indicators: dict[str, Any] = field(default_factory=dict)
    environment_indicators_manifest: dict[str, Any] = field(default_factory=dict)
    api_home: dict[str, Any] = field(default_factory=dict)
    api_page: dict[str, Any] = field(default_factory=dict)
    api_summary: dict[str, Any] = field(default_factory=dict)
    api_detail: dict[str, Any] = field(default_factory=dict)
    api_today_bridge: dict[str, Any] = field(default_factory=dict)
    api_timeline: dict[str, Any] = field(default_factory=dict)
    api_asset_strength: dict[str, Any] = field(default_factory=dict)
    api_state_transition: dict[str, Any] = field(default_factory=dict)
    api_model_background: dict[str, Any] = field(default_factory=dict)
    api_next_day_preview: dict[str, Any] = field(default_factory=dict)
    api_analysis_tabs: dict[str, Any] = field(default_factory=dict)
    api_live_context: dict[str, Any] = field(default_factory=dict)
    api_data_guide: dict[str, Any] = field(default_factory=dict)
    api_dart_summary: dict[str, Any] = field(default_factory=dict)
    api_dart_summary_history: dict[str, Any] = field(default_factory=dict)
    api_breadth_detail: dict[str, Any] = field(default_factory=dict)
    api_breadth_detail_history: dict[str, Any] = field(default_factory=dict)
    api_us_macro_panel: dict[str, Any] = field(default_factory=dict)
    api_us_macro_panel_history: dict[str, Any] = field(default_factory=dict)
    api_timeline_history: dict[str, Any] = field(default_factory=dict)
    api_asset_strength_history: dict[str, Any] = field(default_factory=dict)
    api_state_transition_history: dict[str, Any] = field(default_factory=dict)
    api_next_day_preview_history: dict[str, Any] = field(default_factory=dict)
    source_name: str = "market-analysis-local"
    stale: bool = False
    empty: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def asof(self) -> str | None:
        return (
            self.manifest.get("asof")
            or self.page.get("asof")
            or self.home.get("asof")
            or self.today.get("asof")
            or self.timeline.get("asof")
            or self.timeline_history.get("asof")
            or self.timeline_history.get("as_of_date")
            or self.asset_strength.get("asof")
            or self.asset_strength_history.get("asof")
            or self.asset_strength_history.get("as_of_date")
            or self.state_transition.get("asof")
            or self.model_background.get("asof")
            or self.next_day_preview.get("asof")
            or self.analysis_tabs.get("asof")
            or self.live_context.get("asof")
            or self.data_guide.get("asof")
            or self.dart_summary.get("asof")
            or self.dart_summary.get("reference_date")
            or self.breadth_detail.get("asof")
            or self.us_macro_panel.get("asof")
            or self.environment_indicators.get("asof")
        )


@dataclass
class MarketAnalysisStatus:
    state: str
    asof: str | None
    source_name: str
    age_seconds: int | None
    warning_after_minutes: int
    stale_after_minutes: int
    snapshot_accessible: bool
    warnings: list[str]
    errors: list[str]


class MarketAnalysisMockApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root_dir = Path(settings.market_analysis_dir)
        self.cache_ttl_seconds = max(settings.snapshot_cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: MarketAnalysisBundle | None = None
        self._cache_expires_at = 0.0

    def load_bundle(self, force_refresh: bool = False) -> MarketAnalysisBundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return self._cached_bundle

            try:
                bundle = self._load_bundle_with_fallbacks()
            except MarketAnalysisLoadError as exc:
                if self._cached_bundle is not None:
                    fallback = deepcopy(self._cached_bundle)
                    fallback.stale = True
                    fallback.warnings = list(fallback.warnings) + [
                        "최신 시장 브리핑 데이터를 읽지 못해 마지막 정상 데이터를 표시합니다."
                    ]
                    fallback.errors = exc.errors
                    return fallback
                raise

            self._cached_bundle = bundle
            self._cache_expires_at = now + self.cache_ttl_seconds
            return bundle

    def get_status(self, force_refresh: bool = False) -> MarketAnalysisStatus:
        try:
            bundle = self.load_bundle(force_refresh=force_refresh)
        except MarketAnalysisLoadError as exc:
            return MarketAnalysisStatus(
                state="error",
                asof=self._cached_bundle.asof if self._cached_bundle else None,
                source_name="market-analysis-local",
                age_seconds=self._compute_age_seconds(
                    self._cached_bundle.asof if self._cached_bundle else None
                ),
                warning_after_minutes=90,
                stale_after_minutes=180,
                snapshot_accessible=False,
                warnings=[],
                errors=exc.errors,
            )

        freshness = bundle.manifest.get("freshness") or {}
        warning_after = int(freshness.get("consumer_warning_after_minutes") or 90)
        stale_after = int(freshness.get("consumer_stale_after_minutes") or 180)
        age_seconds = self._compute_age_seconds(bundle.asof)
        warnings = list(bundle.warnings)
        state = "healthy"
        if bundle.empty:
            state = "empty"
            warnings.append("시장 브리핑 데이터가 아직 준비되지 않았습니다.")
        elif bundle.stale or self._is_older_than(age_seconds, stale_after):
            state = "stale"
            warnings.append("시장 브리핑 데이터 업데이트가 지연되고 있습니다.")
        elif self._is_older_than(age_seconds, warning_after):
            state = "warning"
            warnings.append("시장 브리핑 데이터가 기준 주기보다 늦게 갱신되고 있습니다.")
        return MarketAnalysisStatus(
            state=state,
            asof=bundle.asof,
            source_name=bundle.source_name,
            age_seconds=age_seconds,
            warning_after_minutes=warning_after,
            stale_after_minutes=stale_after,
            snapshot_accessible=not bundle.empty,
            warnings=warnings,
            errors=list(bundle.errors),
        )

    def get_api_payload(self, key: str, force_refresh: bool = False) -> dict[str, Any]:
        bundle = self.load_bundle(force_refresh=force_refresh)
        return deepcopy(getattr(bundle, key, {}))

    def _load_bundle_with_fallbacks(self) -> MarketAnalysisBundle:
        errors: list[str] = []
        for loader in self._iter_loaders():
            try:
                return loader()
            except MarketAnalysisLoadError as exc:
                errors.extend(exc.errors)
        raise MarketAnalysisLoadError(
            "Market analysis handoff is temporarily unavailable.",
            errors=errors,
        )

    def _iter_loaders(self):
        use_remote = self.settings.market_analysis_source in REMOTE_SOURCES or bool(
            self.settings.market_analysis_base_url
        )
        if use_remote:
            yield self._load_from_remote_current
        yield self._load_from_local_current

    def _load_from_local_current(self) -> MarketAnalysisBundle:
        return self._load_from_local_directory(self.root_dir, "market-analysis-local")

    def _load_from_remote_current(self) -> MarketAnalysisBundle:
        base_url = self._get_remote_base_url()
        history_base_url = self._get_remote_history_base_url(base_url)
        warnings: list[str] = []
        payloads: dict[str, dict[str, Any]] = {}
        request_token = str(int(time.time()))
        for key, filename in MARKET_ANALYSIS_FILES.items():
            source_base_url = history_base_url if key in HISTORY_MARKET_ANALYSIS_KEYS else base_url
            url = self._with_cache_buster(f"{source_base_url}/{filename}", request_token)
            required = key not in OPTIONAL_MARKET_ANALYSIS_KEYS and key != "manifest"
            payload = self._load_json_url(url, required=required)
            if payload is None:
                if key not in OPTIONAL_MARKET_ANALYSIS_KEYS:
                    warnings.append(f"{filename} 파일을 원격 source에서 읽지 못했습니다.")
                payload = {}
            payloads[key] = payload
        bundle = MarketAnalysisBundle(
            home=payloads["home"],
            today=payloads["today"],
            page=payloads["page"],
            manifest=payloads["manifest"],
            timeline=payloads["timeline"],
            asset_strength=payloads["asset_strength"],
            state_transition=payloads["state_transition"],
            model_background=payloads["model_background"],
            timeline_history=payloads["timeline_history"],
            asset_strength_history=payloads["asset_strength_history"],
            state_transition_history=payloads["state_transition_history"],
            next_day_preview=payloads["next_day_preview"],
            next_day_preview_history=payloads["next_day_preview_history"],
            next_day_preview_manifest=payloads["next_day_preview_manifest"],
            analysis_tabs=payloads["analysis_tabs"],
            live_context=payloads["live_context"],
            data_guide=payloads["data_guide"],
            dart_summary=payloads["dart_summary"],
            dart_summary_history=payloads["dart_summary_history"],
            breadth_detail=payloads["breadth_detail"],
            breadth_detail_history=payloads["breadth_detail_history"],
            us_macro_panel=payloads["us_macro_panel"],
            us_macro_panel_history=payloads["us_macro_panel_history"],
            environment_indicators=payloads["environment_indicators"],
            api_environment_indicators=payloads["api_environment_indicators"],
            environment_indicators_manifest=payloads["environment_indicators_manifest"],
            api_home=payloads["api_home"],
            api_page=payloads["api_page"],
            api_summary=payloads["api_summary"],
            api_detail=payloads["api_detail"],
            api_today_bridge=payloads["api_today_bridge"],
            api_timeline=payloads["api_timeline"],
            api_asset_strength=payloads["api_asset_strength"],
            api_state_transition=payloads["api_state_transition"],
            api_model_background=payloads["api_model_background"],
            api_next_day_preview=payloads["api_next_day_preview"],
            api_analysis_tabs=payloads["api_analysis_tabs"],
            api_live_context=payloads["api_live_context"],
            api_data_guide=payloads["api_data_guide"],
            api_dart_summary=payloads["api_dart_summary"],
            api_dart_summary_history=payloads["api_dart_summary_history"],
            api_breadth_detail=payloads["api_breadth_detail"],
            api_breadth_detail_history=payloads["api_breadth_detail_history"],
            api_us_macro_panel=payloads["api_us_macro_panel"],
            api_us_macro_panel_history=payloads["api_us_macro_panel_history"],
            api_timeline_history=payloads["api_timeline_history"],
            api_asset_strength_history=payloads["api_asset_strength_history"],
            api_state_transition_history=payloads["api_state_transition_history"],
            api_next_day_preview_history=payloads["api_next_day_preview_history"],
            source_name="market-analysis-remote",
            warnings=warnings,
        )
        bundle.empty = not any(
            bool(payload)
            for payload in (
                bundle.home,
                bundle.today,
                bundle.page,
                bundle.api_summary,
                bundle.api_detail,
                bundle.api_today_bridge,
            )
        )
        self._validate_bundle_consistency(bundle)
        return bundle

    def _validate_bundle_consistency(self, bundle: MarketAnalysisBundle) -> None:
        manifest_asof = _normalized_asof(bundle.manifest.get("asof"))
        payload_pairs = [
            ("home", bundle.home),
            ("today", bundle.today),
            ("page", bundle.page),
            ("api_home", bundle.api_home),
            ("api_page", bundle.api_page),
            ("timeline", bundle.timeline),
            ("asset_strength", bundle.asset_strength),
            ("state_transition", bundle.state_transition),
            ("model_background", bundle.model_background),
            ("timeline_history", bundle.timeline_history),
            ("asset_strength_history", bundle.asset_strength_history),
            ("state_transition_history", bundle.state_transition_history),
            ("api_summary", bundle.api_summary),
            ("api_detail", bundle.api_detail),
            ("api_today_bridge", bundle.api_today_bridge),
            ("api_timeline", bundle.api_timeline),
            ("api_asset_strength", bundle.api_asset_strength),
            ("api_state_transition", bundle.api_state_transition),
            ("api_model_background", bundle.api_model_background),
            ("api_analysis_tabs", bundle.api_analysis_tabs),
            ("api_live_context", bundle.api_live_context),
            ("api_data_guide", bundle.api_data_guide),
            ("api_dart_summary", bundle.api_dart_summary),
            ("api_breadth_detail", bundle.api_breadth_detail),
            ("api_us_macro_panel", bundle.api_us_macro_panel),
            ("api_environment_indicators", bundle.api_environment_indicators),
            ("api_timeline_history", bundle.api_timeline_history),
            ("api_asset_strength_history", bundle.api_asset_strength_history),
            ("api_state_transition_history", bundle.api_state_transition_history),
        ]
        strict_mismatches: list[str] = []
        optional_mismatches: list[str] = []
        for key, payload in payload_pairs:
            payload_asof = _payload_asof(payload)
            if manifest_asof and payload_asof and payload_asof != manifest_asof:
                if key in STRICT_MARKET_ANALYSIS_ASOF_KEYS:
                    strict_mismatches.append(f"{key}={payload_asof}")
                else:
                    optional_mismatches.append(f"{key}={payload_asof}")
        if optional_mismatches:
            details = ", ".join(optional_mismatches)
            bundle.warnings.append(
                "시장 분석 보조/히스토리 payload 기준시각이 manifest와 다릅니다: "
                f"manifest={manifest_asof}, {details}"
            )
        if strict_mismatches:
            details = ", ".join(strict_mismatches)
            message = (
                "시장 브리핑 handoff 파일의 기준시각이 서로 다릅니다: "
                f"manifest={manifest_asof}, {details}"
            )
            raise MarketAnalysisLoadError(
                "Market-analysis handoff files are out of sync.",
                errors=[message],
            )

    def _get_remote_base_url(self) -> str:
        base_url = self.settings.market_analysis_base_url.strip().rstrip("/")
        if base_url:
            return base_url
        if self.settings.snapshot_gcs_base_url:
            return self.settings.snapshot_gcs_base_url.rstrip("/") + "/market_analysis/current"
        if self.settings.snapshot_gcs_bucket:
            bucket = self.settings.snapshot_gcs_bucket.strip().removeprefix("gs://")
            return f"https://storage.googleapis.com/{bucket}/market_analysis/current"
        raise MarketAnalysisLoadError(
            "Remote market-analysis source is configured without "
            "MARKET_ANALYSIS_BASE_URL or GCS settings."
        )

    @staticmethod
    def _get_remote_history_base_url(base_url: str) -> str:
        if base_url.endswith("/current"):
            return base_url[: -len("/current")] + "/history"
        return base_url.rstrip("/") + "/history"

    def _load_from_local_directory(self, directory: Path, source_name: str) -> MarketAnalysisBundle:
        if not directory.exists():
            raise MarketAnalysisLoadError(f"Market analysis directory does not exist: {directory}")

        warnings: list[str] = []
        payloads: dict[str, dict[str, Any]] = {}
        for key, filename in MARKET_ANALYSIS_FILES.items():
            path = directory / filename
            if not path.exists():
                if key not in OPTIONAL_MARKET_ANALYSIS_KEYS:
                    warnings.append(f"{filename} 파일이 없습니다.")
                payloads[key] = {}
                continue
            payloads[key] = self._load_json_path(path)

        bundle = MarketAnalysisBundle(
            home=payloads["home"],
            today=payloads["today"],
            page=payloads["page"],
            manifest=payloads["manifest"],
            timeline=payloads["timeline"],
            asset_strength=payloads["asset_strength"],
            state_transition=payloads["state_transition"],
            model_background=payloads["model_background"],
            timeline_history=payloads["timeline_history"],
            asset_strength_history=payloads["asset_strength_history"],
            state_transition_history=payloads["state_transition_history"],
            next_day_preview=payloads["next_day_preview"],
            next_day_preview_history=payloads["next_day_preview_history"],
            next_day_preview_manifest=payloads["next_day_preview_manifest"],
            analysis_tabs=payloads["analysis_tabs"],
            live_context=payloads["live_context"],
            data_guide=payloads["data_guide"],
            dart_summary=payloads["dart_summary"],
            dart_summary_history=payloads["dart_summary_history"],
            breadth_detail=payloads["breadth_detail"],
            breadth_detail_history=payloads["breadth_detail_history"],
            us_macro_panel=payloads["us_macro_panel"],
            us_macro_panel_history=payloads["us_macro_panel_history"],
            environment_indicators=payloads["environment_indicators"],
            api_environment_indicators=payloads["api_environment_indicators"],
            environment_indicators_manifest=payloads["environment_indicators_manifest"],
            api_home=payloads["api_home"],
            api_page=payloads["api_page"],
            api_summary=payloads["api_summary"],
            api_detail=payloads["api_detail"],
            api_today_bridge=payloads["api_today_bridge"],
            api_timeline=payloads["api_timeline"],
            api_asset_strength=payloads["api_asset_strength"],
            api_state_transition=payloads["api_state_transition"],
            api_model_background=payloads["api_model_background"],
            api_next_day_preview=payloads["api_next_day_preview"],
            api_analysis_tabs=payloads["api_analysis_tabs"],
            api_live_context=payloads["api_live_context"],
            api_data_guide=payloads["api_data_guide"],
            api_dart_summary=payloads["api_dart_summary"],
            api_dart_summary_history=payloads["api_dart_summary_history"],
            api_breadth_detail=payloads["api_breadth_detail"],
            api_breadth_detail_history=payloads["api_breadth_detail_history"],
            api_us_macro_panel=payloads["api_us_macro_panel"],
            api_us_macro_panel_history=payloads["api_us_macro_panel_history"],
            api_timeline_history=payloads["api_timeline_history"],
            api_asset_strength_history=payloads["api_asset_strength_history"],
            api_state_transition_history=payloads["api_state_transition_history"],
            api_next_day_preview_history=payloads["api_next_day_preview_history"],
            source_name=source_name,
            warnings=warnings,
        )
        bundle.empty = not any(
            bool(payload)
            for payload in (
                bundle.home,
                bundle.today,
                bundle.page,
                bundle.api_summary,
                bundle.api_detail,
                bundle.api_today_bridge,
            )
        )
        self._validate_bundle_consistency(bundle)
        return bundle

    @staticmethod
    def _with_cache_buster(url: str, token: str) -> str:
        parts = urlsplit(url)
        if parts.scheme == "file" or not parts.scheme:
            return url
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["ts"] = token
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    @staticmethod
    def _load_json_path(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise MarketAnalysisLoadError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

    @staticmethod
    def _load_json_url(url: str, *, required: bool = True) -> dict[str, Any] | None:
        request = Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = response.read().decode("utf-8-sig")
        except URLError as exc:
            if required:
                raise MarketAnalysisLoadError(
                    f"Failed to fetch market-analysis handoff: {url}"
                ) from exc
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MarketAnalysisLoadError(f"Invalid JSON fetched from {url}: {exc.msg}") from exc

    @staticmethod
    def _compute_age_seconds(value: str | None) -> int | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(
            int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()),
            0,
        )

    @staticmethod
    def _is_older_than(age_seconds: int | None, minutes: int) -> bool:
        if age_seconds is None:
            return False
        return age_seconds > minutes * 60
