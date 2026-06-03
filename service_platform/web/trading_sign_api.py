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

TRADING_SIGN_FILENAMES = {
    "overview": "tradingsign_overview.json",
    "detail": "tradingsign_model_detail.json",
    "manifest": "tradingsign_manifest.json",
}
DEFAULT_TRADING_SIGN_EXTERNAL_CURRENT_DIR = Path(
    r"D:\Quant\trading_sign\service_platform\web\public_data\current"
)
REMOTE_SOURCES = {"remote", "http", "gcs"}


class TradingSignLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class TradingSignBundle:
    overview: dict[str, Any]
    detail: dict[str, Any]
    manifest: dict[str, Any]
    source_name: str
    stale: bool = False
    empty: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def asof(self) -> str | None:
        return self.overview.get("asof") or self.detail.get("asof") or self.manifest.get("asof")

    @property
    def generated_at(self) -> str | None:
        return (
            self.overview.get("generated_at")
            or self.detail.get("generated_at")
            or self.manifest.get("generated_at")
        )


@dataclass
class TradingSignStatus:
    state: str
    source_name: str
    asof: str | None
    generated_at: str | None
    age_seconds: int | None
    stale_after_hours: int
    warnings: list[str]
    errors: list[str]
    model_count: int
    signal_count: int
    snapshot_accessible: bool


class TradingSignSnapshotApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root_dir = Path(settings.public_data_dir) / "trading_sign" / "current"
        self.external_root_dir = DEFAULT_TRADING_SIGN_EXTERNAL_CURRENT_DIR
        self.cache_ttl_seconds = max(settings.snapshot_cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: TradingSignBundle | None = None
        self._cache_expires_at = 0.0
        self._last_errors: list[str] = []

    def load_bundle(self, force_refresh: bool = False) -> TradingSignBundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return self._cached_bundle

            try:
                bundle = self._load_bundle_with_fallbacks()
            except TradingSignLoadError as exc:
                self._last_errors = exc.errors
                if self._cached_bundle is not None:
                    stale_bundle = deepcopy(self._cached_bundle)
                    stale_bundle.stale = True
                    stale_bundle.warnings = list(stale_bundle.warnings) + [
                        "최신 일간 신호를 읽지 못해 이전 정상 데이터를 표시합니다."
                    ]
                    stale_bundle.errors = exc.errors
                    return stale_bundle
                raise

            self._cached_bundle = bundle
            self._cache_expires_at = now + self.cache_ttl_seconds
            self._last_errors = list(bundle.errors)
            return bundle

    def get_status(self, force_refresh: bool = False) -> TradingSignStatus:
        try:
            bundle = self.load_bundle(force_refresh=force_refresh)
        except TradingSignLoadError as exc:
            return TradingSignStatus(
                state="error",
                source_name=self._configured_source_name(),
                asof=self._cached_bundle.asof if self._cached_bundle else None,
                generated_at=self._cached_bundle.generated_at if self._cached_bundle else None,
                age_seconds=self._compute_age_seconds(
                    self._cached_bundle.generated_at if self._cached_bundle else None
                ),
                stale_after_hours=self.settings.snapshot_stale_after_hours,
                warnings=[],
                errors=exc.errors,
                model_count=0,
                signal_count=0,
                snapshot_accessible=False,
            )

        age_seconds = self._compute_age_seconds(bundle.generated_at)
        warnings = list(bundle.warnings)
        state = "healthy"
        if bundle.empty:
            state = "empty"
            warnings.append("일간 신호 데이터가 아직 준비되지 않았습니다.")
        elif bundle.stale or self._is_age_stale(age_seconds):
            state = "stale"
            if self._is_age_stale(age_seconds):
                warnings.append(
                    "일간 신호 생성 시각이 "
                    f"{self.settings.snapshot_stale_after_hours}시간을 넘어 오래되었습니다."
                )

        summary = bundle.overview.get("summary") or {}
        return TradingSignStatus(
            state=state,
            source_name=bundle.source_name,
            asof=bundle.asof,
            generated_at=bundle.generated_at,
            age_seconds=age_seconds,
            stale_after_hours=self.settings.snapshot_stale_after_hours,
            warnings=warnings,
            errors=list(bundle.errors),
            model_count=int(summary.get("model_count") or len(bundle.detail.get("models", []))),
            signal_count=int(summary.get("signal_count") or 0),
            snapshot_accessible=True,
        )

    def get_model_detail_map(self, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        bundle = self.load_bundle(force_refresh=force_refresh)
        models = bundle.detail.get("models") or []
        return {
            str(model.get("model_code") or "").strip().upper(): model
            for model in models
            if str(model.get("model_code") or "").strip()
        }

    def _load_bundle_with_fallbacks(self) -> TradingSignBundle:
        errors: list[str] = []
        for loader in self._iter_loaders():
            try:
                bundle = loader()
            except TradingSignLoadError as exc:
                errors.extend(exc.errors)
                continue
            if errors:
                bundle.warnings = list(bundle.warnings) + [
                    "원격 일간 신호 current를 읽지 못해 fallback 데이터를 사용합니다."
                ]
                bundle.errors = list(errors) + list(bundle.errors)
            return bundle
        raise TradingSignLoadError(
            "일간 신호 스냅샷을 찾을 수 없습니다.",
            errors=errors or ["일간 신호 스냅샷을 찾을 수 없습니다."],
        )

    def _iter_loaders(self):
        use_remote = self.settings.snapshot_source in REMOTE_SOURCES or bool(
            self.settings.snapshot_gcs_base_url
        )
        if use_remote:
            yield self._load_from_remote_current
        yield lambda: self._load_bundle_from_dir(
            self.root_dir, "service-local trading_sign current"
        )
        if self.settings.app_env != "test" and self.external_root_dir.exists():
            yield lambda: self._load_bundle_from_dir(
                self.external_root_dir,
                "thread-local trading_sign current",
            )

    def _load_from_remote_current(self) -> TradingSignBundle:
        base_url = self._get_remote_base_url().rstrip("/")
        payloads: dict[str, Any] = {}
        request_token = str(int(time.time()))
        errors: list[str] = []
        for key, filename in TRADING_SIGN_FILENAMES.items():
            url = self._with_cache_buster(f"{base_url}/{filename}", request_token)
            payload = self._load_json_url(url)
            if payload is None:
                errors.append(f"{filename} 파일을 원격 source에서 읽지 못했습니다.")
                continue
            payloads[key] = payload

        # Keep rendering possible as long as detail exists.
        # During remote republish, overview/manifest can be briefly unavailable.
        if "detail" not in payloads:
            raise TradingSignLoadError(
                "일간 신호 핵심 스냅샷 파일이 없어 블록을 만들 수 없습니다.",
                errors=errors or ["일간 신호 핵심 스냅샷 파일이 없습니다."],
            )
        warnings: list[str] = []
        if "overview" not in payloads:
            warnings.append("overview 파일이 없어 detail 기준으로 일간 신호를 표시합니다.")
        if "manifest" not in payloads:
            warnings.append("manifest 파일이 없어 detail 기준으로 일간 신호를 표시합니다.")

        detail_models = payloads["detail"].get("models") or []
        return TradingSignBundle(
            overview=payloads.get("overview", {}),
            detail=payloads.get("detail", {}),
            manifest=payloads.get("manifest", {}),
            source_name=f"remote:{base_url}",
            empty=len(detail_models) == 0,
            warnings=warnings,
            errors=[],
        )

    def _get_remote_base_url(self) -> str:
        base_url = self.settings.snapshot_gcs_base_url.strip().rstrip("/")
        if base_url:
            return base_url + "/trading_sign/current"
        raise TradingSignLoadError(
            "Remote trading_sign source is configured without SNAPSHOT_GCS_BASE_URL."
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

    def _load_json_url(self, url: str) -> dict[str, Any] | None:
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
                return json.loads(response.read().decode("utf-8-sig"))
        except (OSError, URLError, json.JSONDecodeError):
            return None

    def _load_bundle_from_dir(self, directory: Path, source_name: str) -> TradingSignBundle:
        if not directory.exists():
            raise TradingSignLoadError(
                f"{directory} 경로가 없어 일간 신호 스냅샷을 읽을 수 없습니다.",
                errors=[f"{directory} 경로가 없어 일간 신호 스냅샷을 읽을 수 없습니다."],
            )

        payloads: dict[str, Any] = {}
        errors: list[str] = []
        for key, filename in TRADING_SIGN_FILENAMES.items():
            target = directory / filename
            if not target.exists():
                errors.append(f"{target} 파일이 없습니다.")
                continue
            payloads[key] = self._read_json(target)

        if "detail" not in payloads:
            raise TradingSignLoadError(
                "일간 신호 핵심 스냅샷 파일이 없어 블록을 만들 수 없습니다.",
                errors=errors or ["일간 신호 핵심 스냅샷 파일이 없습니다."],
            )
        warnings: list[str] = []
        if "overview" not in payloads:
            warnings.append("overview 파일이 없어 detail 기준으로 일간 신호를 표시합니다.")
        if "manifest" not in payloads:
            warnings.append("manifest 파일이 없어 detail 기준으로 일간 신호를 표시합니다.")

        detail_models = payloads["detail"].get("models") or []
        return TradingSignBundle(
            overview=payloads.get("overview", {}),
            detail=payloads.get("detail", {}),
            manifest=payloads.get("manifest", {}),
            source_name=source_name,
            empty=len(detail_models) == 0,
            warnings=warnings,
            errors=[],
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _configured_source_name(self) -> str:
        if self.settings.snapshot_source in REMOTE_SOURCES or self.settings.snapshot_gcs_base_url:
            base_url = self.settings.snapshot_gcs_base_url.strip().rstrip("/")
            if base_url:
                return f"remote:{base_url}/trading_sign/current"
            return "remote:trading_sign/current"
        if self.settings.app_env != "test" and self.external_root_dir.exists():
            return "thread-local trading_sign current"
        return "service-local trading_sign current"

    def _compute_age_seconds(self, generated_at: str | None) -> int | None:
        if not generated_at:
            return None
        normalized = generated_at.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - parsed.astimezone(timezone.utc)
        return max(int(delta.total_seconds()), 0)

    def _is_age_stale(self, age_seconds: int | None) -> bool:
        if age_seconds is None:
            return False
        return age_seconds > self.settings.snapshot_stale_after_hours * 3600
