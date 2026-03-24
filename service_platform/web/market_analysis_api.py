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
    "api_home": "api_v1_market_analysis_home.json",
    "api_page": "api_v1_market_analysis_page.json",
    "api_summary": "api_v1_market_analysis_summary.json",
    "api_detail": "api_v1_market_analysis_detail.json",
    "api_today_bridge": "api_v1_market_analysis_today_bridge.json",
}
REMOTE_SOURCES = {"remote", "http", "gcs"}


def _normalized_asof(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_asof(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    return _normalized_asof(payload.get("asof"))


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
                bundle = self._load_bundle_with_fallbacks()
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
        warnings: list[str] = []
        payloads: dict[str, dict[str, Any]] = {}
        request_token = str(int(time.time()))
        for key, filename in MARKET_ANALYSIS_FILES.items():
            url = self._with_cache_buster(f"{base_url}/{filename}", request_token)
            required = key != "manifest"
            payload = self._load_json_url(url, required=required)
            if payload is None:
                warnings.append(f"{filename} 파일을 원격 source에서 읽지 못했습니다.")
                payload = {}
            payloads[key] = payload
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
            ("api_summary", bundle.api_summary),
            ("api_detail", bundle.api_detail),
            ("api_today_bridge", bundle.api_today_bridge),
        ]
        mismatches: list[str] = []
        for key, payload in payload_pairs:
            payload_asof = _payload_asof(payload)
            if manifest_asof and payload_asof and payload_asof != manifest_asof:
                mismatches.append(f"{key}={payload_asof}")
        if mismatches:
            details = ", ".join(mismatches)
            message = (
                "시장분석 handoff 파일의 기준시각이 서로 다릅니다: "
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

    def _load_from_local_directory(self, directory: Path, source_name: str) -> MarketAnalysisBundle:
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
            payloads[key] = self._load_json_path(path)

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
