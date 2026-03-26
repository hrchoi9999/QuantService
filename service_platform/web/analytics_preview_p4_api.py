from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

DEFAULT_ANALYTICS_PREVIEW_P4_BUNDLE_DIR = (
    Path(__file__).resolve().parent / "internal_preview" / "analytics_p4"
)
PREVIEW_P4_BUNDLE_FILES = {
    "asset_exposure_detail": "asset_exposure_detail_20260325.json",
    "change_impact": "change_impact_20260325.json",
}


class AnalyticsPreviewP4LoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class AnalyticsPreviewP4Bundle:
    manifest: dict[str, Any] = field(default_factory=dict)
    asset_exposure_detail: dict[str, Any] = field(default_factory=dict)
    change_impact: dict[str, Any] = field(default_factory=dict)
    source_name: str = "analytics-preview-p4-local"
    errors: list[str] = field(default_factory=list)

    @property
    def asof(self) -> str | None:
        return (
            self.manifest.get("asof")
            or (self.asset_exposure_detail.get("meta") or {}).get("asof")
            or (self.change_impact.get("meta") or {}).get("asof")
        )


class AnalyticsPreviewP4Api:
    def __init__(self, *, root_dir: Path | None = None, cache_ttl_seconds: int = 60) -> None:
        configured_dir = os.getenv("ANALYTICS_PREVIEW_P4_BUNDLE_DIR", "").strip()
        self.root_dir = (
            Path(configured_dir)
            if configured_dir
            else (root_dir or DEFAULT_ANALYTICS_PREVIEW_P4_BUNDLE_DIR)
        )
        self.cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: AnalyticsPreviewP4Bundle | None = None
        self._cache_expires_at = 0.0

    def load_bundle(self, force_refresh: bool = False) -> AnalyticsPreviewP4Bundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return deepcopy(self._cached_bundle)

            bundle = self._load_from_directory(self.root_dir)
            self._cached_bundle = deepcopy(bundle)
            self._cache_expires_at = now + self.cache_ttl_seconds
            return bundle

    def _load_from_directory(self, root_dir: Path) -> AnalyticsPreviewP4Bundle:
        manifest_path = root_dir / "bundle_manifest_20260325.json"
        manifest = self._load_json(manifest_path)
        self._validate_meta(manifest, manifest_path.name)

        payloads: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for key, default_name in PREVIEW_P4_BUNDLE_FILES.items():
            file_path = self._resolve_payload_path(root_dir, manifest, key, default_name)
            payload = self._load_json(file_path)
            self._validate_meta(payload.get("meta") or {}, file_path.name)
            payloads[key] = payload
            payload_asof = (payload.get("meta") or {}).get("asof")
            manifest_asof = manifest.get("asof")
            if payload_asof and manifest_asof and payload_asof != manifest_asof:
                errors.append(
                    f"{file_path.name} 기준일({payload_asof})이 "
                    f"manifest 기준일({manifest_asof})과 다릅니다."
                )

        if errors:
            raise AnalyticsPreviewP4LoadError(
                "Preview bundle files are out of sync.",
                errors=errors,
            )

        return AnalyticsPreviewP4Bundle(
            manifest=manifest,
            asset_exposure_detail=payloads["asset_exposure_detail"],
            change_impact=payloads["change_impact"],
        )

    def _resolve_payload_path(
        self,
        root_dir: Path,
        manifest: dict[str, Any],
        key: str,
        default_name: str,
    ) -> Path:
        file_entry = ((manifest.get("files") or {}).get(key) or "").strip()
        if not file_entry:
            return root_dir / default_name

        candidate = Path(file_entry)
        if self._looks_like_windows_absolute_path(file_entry):
            candidate = Path(candidate.name)
        if not candidate.is_absolute():
            candidate = root_dir / candidate
        if candidate.exists():
            return candidate
        return root_dir / default_name

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise AnalyticsPreviewP4LoadError(
                f"Preview bundle file not found: {path}",
                errors=[f"파일을 찾을 수 없습니다: {path}"],
            ) from exc
        except json.JSONDecodeError as exc:
            raise AnalyticsPreviewP4LoadError(
                f"Invalid preview bundle JSON: {path}",
                errors=[f"JSON 형식이 올바르지 않습니다: {path} ({exc})"],
            ) from exc

    @staticmethod
    def _looks_like_windows_absolute_path(value: str) -> bool:
        return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}

    def _validate_meta(self, payload_meta: dict[str, Any], label: str) -> None:
        internal_preview_only = bool(payload_meta.get("internal_preview_only"))
        web_publish_enabled = bool(payload_meta.get("web_publish_enabled"))
        if not internal_preview_only:
            raise AnalyticsPreviewP4LoadError(
                f"{label} is not marked as internal preview only.",
                errors=[f"{label} 파일은 internal_preview_only=true 여야 합니다."],
            )
        if web_publish_enabled:
            raise AnalyticsPreviewP4LoadError(
                f"{label} is marked as publish enabled.",
                errors=[f"{label} 파일은 web_publish_enabled=false 여야 합니다."],
            )
