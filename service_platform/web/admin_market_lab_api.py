from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

DEFAULT_ADMIN_MARKET_CURRENT_DIR = Path(
    r"D:\QuantMarket\service_platform\web\public_data\handoff\quantservice\admin_market\current"
)
DEFAULT_ADMIN_MARKET_LAB_DIR = Path(r"D:\QuantMarket\_tmp\admin_validation\admin_handoff")
DEFAULT_ADMIN_MARKET_SNAPSHOT_DIR = Path(r"D:\QuantMarket\_tmp\admin_validation\admin_snapshot")
DEFAULT_INTERNAL_ADMIN_MARKET_LAB_DIR = (
    Path(__file__).resolve().parent / "internal_preview" / "admin_market_lab"
)
ADMIN_MARKET_FILES = {
    "timeline": "admin_market_timeline.json",
    "asset_strength": "admin_market_asset_strength.json",
    "state_transition": "admin_market_state_transition.json",
    "model_background": "admin_market_model_background.json",
}
ADMIN_MARKET_INTRADAY_FILES = {
    "summary": "admin_market_intraday_summary.json",
    "detail": "admin_market_intraday_detail.json",
}
ADMIN_MARKET_INTRADAY_MANIFEST = "admin_market_intraday_manifest.json"


class AdminMarketLabLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class AdminMarketLabBundle:
    manifest: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    asset_strength: dict[str, Any] = field(default_factory=dict)
    state_transition: dict[str, Any] = field(default_factory=dict)
    model_background: dict[str, Any] = field(default_factory=dict)
    intraday_manifest: dict[str, Any] = field(default_factory=dict)
    intraday_summary: dict[str, Any] = field(default_factory=dict)
    intraday_detail: dict[str, Any] = field(default_factory=dict)
    source_dir: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def asof(self) -> str | None:
        return (
            self.manifest.get("asof")
            or self.timeline.get("asof")
            or self.asset_strength.get("asof")
            or self.state_transition.get("asof")
            or self.model_background.get("asof")
        )

    @property
    def intraday_asof(self) -> str | None:
        return (
            self.intraday_manifest.get("asof")
            or self.intraday_summary.get("asof")
            or self.intraday_detail.get("asof")
        )


class AdminMarketLabApi:
    def __init__(self, *, root_dir: Path | None = None, cache_ttl_seconds: int = 60) -> None:
        configured_dir = os.getenv("ADMIN_MARKET_LAB_DIR", "").strip()
        if configured_dir:
            self.root_candidates = [Path(configured_dir)]
        elif root_dir is not None:
            self.root_candidates = [root_dir]
        else:
            self.root_candidates = [
                DEFAULT_ADMIN_MARKET_CURRENT_DIR,
                DEFAULT_ADMIN_MARKET_LAB_DIR,
                DEFAULT_ADMIN_MARKET_SNAPSHOT_DIR,
                DEFAULT_INTERNAL_ADMIN_MARKET_LAB_DIR,
            ]
        self.cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: AdminMarketLabBundle | None = None
        self._cache_expires_at = 0.0

    def load_bundle(self, force_refresh: bool = False) -> AdminMarketLabBundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return deepcopy(self._cached_bundle)

            bundle = self._load_from_candidates()
            self._cached_bundle = deepcopy(bundle)
            self._cache_expires_at = now + self.cache_ttl_seconds
            return bundle

    def _load_from_candidates(self) -> AdminMarketLabBundle:
        errors: list[str] = []
        for candidate in self.root_candidates:
            if candidate is None:
                continue
            try:
                return self._load_from_directory(candidate)
            except AdminMarketLabLoadError as exc:
                errors.extend(exc.errors)
        raise AdminMarketLabLoadError(
            "Admin market lab bundle unavailable.",
            errors=errors or ["admin market data unavailable"],
        )

    def _load_from_directory(self, root_dir: Path) -> AdminMarketLabBundle:
        manifest_path = root_dir / "admin_market_manifest.json"
        manifest = self._load_json(manifest_path)
        self._validate_manifest(manifest, manifest_path.name)

        payloads: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for key, default_name in ADMIN_MARKET_FILES.items():
            file_path = self._resolve_payload_path(root_dir, manifest, key, default_name)
            payload = self._load_json(file_path)
            payloads[key] = payload
            payload_asof = payload.get("asof")
            manifest_asof = manifest.get("asof")
            if payload_asof and manifest_asof and payload_asof != manifest_asof:
                errors.append(
                    f"{file_path.name} 기준시각({payload_asof})이 "
                    f"manifest 기준시각({manifest_asof})과 다릅니다."
                )

        intraday_manifest, intraday_summary, intraday_detail = self._load_intraday_optional(
            root_dir
        )

        if errors:
            raise AdminMarketLabLoadError(
                "Admin market lab files are out of sync.",
                errors=errors,
            )

        return AdminMarketLabBundle(
            manifest=manifest,
            timeline=payloads["timeline"],
            asset_strength=payloads["asset_strength"],
            state_transition=payloads["state_transition"],
            model_background=payloads["model_background"],
            intraday_manifest=intraday_manifest,
            intraday_summary=intraday_summary,
            intraday_detail=intraday_detail,
            source_dir=str(root_dir),
        )

    def _load_intraday_optional(
        self, root_dir: Path
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        intraday_manifest_path = root_dir / ADMIN_MARKET_INTRADAY_MANIFEST
        if not intraday_manifest_path.exists():
            return {}, {}, {}

        manifest = self._load_json(intraday_manifest_path)
        self._validate_manifest(manifest, intraday_manifest_path.name)

        payloads: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for key, default_name in ADMIN_MARKET_INTRADAY_FILES.items():
            file_path = self._resolve_payload_path(root_dir, manifest, key, default_name)
            payload = self._load_json(file_path)
            payloads[key] = payload
            payload_asof = payload.get("asof")
            manifest_asof = manifest.get("asof")
            if payload_asof and manifest_asof and payload_asof != manifest_asof:
                errors.append(
                    f"{file_path.name} 기준시각({payload_asof})이 "
                    f"intraday manifest 기준시각({manifest_asof})과 다릅니다."
                )

        if errors:
            raise AdminMarketLabLoadError(
                "Admin intraday market files are out of sync.",
                errors=errors,
            )

        return manifest, payloads.get("summary", {}), payloads.get("detail", {})

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
        if not candidate.is_absolute():
            if self._looks_like_windows_absolute_path(file_entry):
                candidate = root_dir / candidate.name
            else:
                candidate = root_dir / candidate
        elif not candidate.exists():
            candidate = root_dir / candidate.name
        if candidate.exists():
            return candidate
        return root_dir / default_name

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise AdminMarketLabLoadError(
                f"Admin market lab file not found: {path}",
                errors=[f"파일을 찾을 수 없습니다: {path}"],
            ) from exc
        except json.JSONDecodeError as exc:
            raise AdminMarketLabLoadError(
                f"Invalid admin market lab JSON: {path}",
                errors=[f"JSON 형식이 올바르지 않습니다: {path} ({exc})"],
            ) from exc

    @staticmethod
    def _looks_like_windows_absolute_path(value: str) -> bool:
        return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}

    def _validate_manifest(self, manifest: dict[str, Any], label: str) -> None:
        visibility = str(manifest.get("visibility") or "").strip().lower()
        if visibility != "admin_only_pre_publish":
            raise AdminMarketLabLoadError(
                f"{label} has invalid visibility.",
                errors=[f"{label} 파일은 visibility=admin_only_pre_publish 여야 합니다."],
            )
