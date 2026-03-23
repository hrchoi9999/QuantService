from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from service_platform.shared.config import Settings

MARKET_ANALYSIS_FILES = {
    "home": "quantservice_market_home.json",
    "today": "quantservice_market_today.json",
    "page": "quantservice_market_page.json",
    "manifest": "quantservice_market_manifest.json",
    "api_home": "api_v1_market_analysis_home.json",
    "api_page": "api_v1_market_analysis_page.json",
    "api_summary": "api_v1_market_analysis_summary.json",
    "api_detail": "api_v1_market_analysis_detail.json",
    "api_today_bridge": "api_v1_market_analysis_today_bridge.json",
}


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
    api_home: dict[str, Any] = field(default_factory=dict)
    api_page: dict[str, Any] = field(default_factory=dict)
    api_summary: dict[str, Any] = field(default_factory=dict)
    api_detail: dict[str, Any] = field(default_factory=dict)
    api_today_bridge: dict[str, Any] = field(default_factory=dict)
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
                return deepcopy(self._cached_bundle)

            try:
                bundle = self._load_from_directory(self.root_dir)
            except MarketAnalysisLoadError as exc:
                if self._cached_bundle is not None:
                    fallback = deepcopy(self._cached_bundle)
                    fallback.stale = True
                    fallback.warnings = list(fallback.warnings) + [
                        "최신 시장분석 handoff를 읽지 못해 마지막 정상 데이터를 표시합니다."
                    ]
                    fallback.errors = exc.errors
                    return fallback
                raise

            self._cached_bundle = deepcopy(bundle)
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
            warnings.append("시장분석 handoff 데이터가 아직 준비되지 않았습니다.")
        elif bundle.stale or self._is_older_than(age_seconds, stale_after):
            state = "stale"
            warnings.append("시장분석 데이터 업데이트가 지연되고 있습니다.")
        elif self._is_older_than(age_seconds, warning_after):
            state = "warning"
            warnings.append("시장분석 데이터가 기준 주기보다 늦게 갱신되고 있습니다.")
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

    def _load_from_directory(self, directory: Path) -> MarketAnalysisBundle:
        if not directory.exists():
            raise MarketAnalysisLoadError(f"Market analysis directory does not exist: {directory}")

        warnings: list[str] = []
        payloads: dict[str, dict[str, Any]] = {}
        for key, filename in MARKET_ANALYSIS_FILES.items():
            path = directory / filename
            if not path.exists():
                warnings.append(f"{filename} 파일이 없습니다.")
                payloads[key] = {}
                continue
            payloads[key] = self._load_json(path)

        bundle = MarketAnalysisBundle(
            home=payloads["home"],
            today=payloads["today"],
            page=payloads["page"],
            manifest=payloads["manifest"],
            api_home=payloads["api_home"],
            api_page=payloads["api_page"],
            api_summary=payloads["api_summary"],
            api_detail=payloads["api_detail"],
            api_today_bridge=payloads["api_today_bridge"],
            source_name="market-analysis-local",
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
        return bundle

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise MarketAnalysisLoadError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

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
