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

USER_SNAPSHOT_FILES = {
    "user_models": "user_model_catalog.json",
    "recommendation_today": "user_recommendation_report.json",
    "performance_summary": "user_performance_summary.json",
    "recent_changes": "user_recent_changes.json",
    "publish_status": "publish_manifest.json",
}


class UserSnapshotLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class UserSnapshotBundle:
    user_models: dict[str, Any]
    recommendation_today: dict[str, Any]
    performance_summary: dict[str, Any]
    recent_changes: dict[str, Any]
    publish_status: dict[str, Any]
    source_name: str
    stale: bool = False
    empty: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def as_of_date(self) -> str | None:
        return self.publish_status.get("as_of_date") or self.recommendation_today.get("as_of_date")

    @property
    def generated_at(self) -> str | None:
        return self.publish_status.get("generated_at") or self.recommendation_today.get(
            "generated_at"
        )


@dataclass
class UserSnapshotStatus:
    state: str
    source_name: str
    as_of_date: str | None
    generated_at: str | None
    age_seconds: int | None
    stale_after_hours: int
    warnings: list[str]
    errors: list[str]
    model_count: int
    report_count: int
    snapshot_accessible: bool


class UserSnapshotMockApi:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root_dir = Path(settings.user_snapshot_dir)
        self.cache_ttl_seconds = max(settings.snapshot_cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: UserSnapshotBundle | None = None
        self._cache_expires_at = 0.0
        self._last_errors: list[str] = []

    def load_bundle(self, force_refresh: bool = False) -> UserSnapshotBundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return deepcopy(self._cached_bundle)

            try:
                bundle = self._load_from_directory(self.root_dir, source_name="snapshot-local")
            except UserSnapshotLoadError as exc:
                self._last_errors = exc.errors
                if self._cached_bundle is not None:
                    stale_bundle = deepcopy(self._cached_bundle)
                    stale_bundle.stale = True
                    stale_bundle.warnings = list(stale_bundle.warnings) + [
                        "?? ???? ???? ?? ??? ?? ???? ???? ????."
                    ]
                    stale_bundle.errors = exc.errors
                    return stale_bundle
                raise

            self._cached_bundle = deepcopy(bundle)
            self._cache_expires_at = now + self.cache_ttl_seconds
            self._last_errors = []
            return bundle

    def get_status(self, force_refresh: bool = False) -> UserSnapshotStatus:
        try:
            bundle = self.load_bundle(force_refresh=force_refresh)
        except UserSnapshotLoadError as exc:
            return UserSnapshotStatus(
                state="error",
                source_name="snapshot-local",
                as_of_date=self._cached_bundle.as_of_date if self._cached_bundle else None,
                generated_at=self._cached_bundle.generated_at if self._cached_bundle else None,
                age_seconds=self._compute_age_seconds(
                    self._cached_bundle.generated_at if self._cached_bundle else None
                ),
                stale_after_hours=self.settings.snapshot_stale_after_hours,
                warnings=[],
                errors=exc.errors,
                model_count=(
                    len(self._cached_bundle.user_models.get("models", []))
                    if self._cached_bundle
                    else 0
                ),
                report_count=(
                    len(self._cached_bundle.recommendation_today.get("reports", []))
                    if self._cached_bundle
                    else 0
                ),
                snapshot_accessible=False,
            )

        age_seconds = self._compute_age_seconds(bundle.generated_at)
        warnings = list(bundle.warnings)
        state = "healthy"
        if bundle.empty:
            state = "empty"
            warnings.append("??? ???? ??? ???? ?? ????.")
        elif bundle.stale or self._is_age_stale(age_seconds):
            state = "stale"
            if self._is_age_stale(age_seconds):
                warnings.append(
                    f"??? ?? ??? {self.settings.snapshot_stale_after_hours}?? ???? ???????."
                )
        return UserSnapshotStatus(
            state=state,
            source_name=bundle.source_name,
            as_of_date=bundle.as_of_date,
            generated_at=bundle.generated_at,
            age_seconds=age_seconds,
            stale_after_hours=self.settings.snapshot_stale_after_hours,
            warnings=warnings,
            errors=list(bundle.errors),
            model_count=len(bundle.user_models.get("models", [])),
            report_count=len(bundle.recommendation_today.get("reports", [])),
            snapshot_accessible=True,
        )

    def get_user_models(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).user_models

    def get_recommendation_today(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).recommendation_today

    def get_recommendation_by_profile(
        self, service_profile: str, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        bundle = self.load_bundle(force_refresh=force_refresh)
        for report in bundle.recommendation_today.get("reports", []):
            if report.get("service_profile") == service_profile:
                return {
                    "as_of_date": bundle.recommendation_today.get("as_of_date"),
                    "generated_at": bundle.recommendation_today.get("generated_at"),
                    "current_market_regime": bundle.recommendation_today.get(
                        "current_market_regime"
                    ),
                    "report": report,
                }
        return None

    def get_performance_summary(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).performance_summary

    def get_recent_changes(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).recent_changes

    def get_publish_status(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).publish_status

    def _load_from_directory(self, directory: Path, *, source_name: str) -> UserSnapshotBundle:
        if not directory.exists():
            raise UserSnapshotLoadError(f"Snapshot directory does not exist: {directory}")

        payloads = {
            key: self._load_json(directory / filename)
            for key, filename in USER_SNAPSHOT_FILES.items()
        }
        self._validate_payloads(payloads)
        bundle = UserSnapshotBundle(
            user_models=payloads["user_models"],
            recommendation_today=payloads["recommendation_today"],
            performance_summary=payloads["performance_summary"],
            recent_changes=payloads["recent_changes"],
            publish_status=payloads["publish_status"],
            source_name=source_name,
        )
        bundle.empty = self._is_bundle_empty(bundle)
        return bundle

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise UserSnapshotLoadError(f"Missing snapshot file: {path.name}")
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise UserSnapshotLoadError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

    def _validate_payloads(self, payloads: dict[str, dict[str, Any]]) -> None:
        errors: list[str] = []
        if not isinstance(payloads["user_models"].get("models"), list):
            errors.append("user_model_catalog.json: models must be a list")
        if not isinstance(payloads["recommendation_today"].get("reports"), list):
            errors.append("user_recommendation_report.json: reports must be a list")
        if not isinstance(payloads["performance_summary"].get("models"), list):
            errors.append("user_performance_summary.json: models must be a list")
        if not isinstance(payloads["recent_changes"].get("changes"), list):
            errors.append("user_recent_changes.json: changes must be a list")
        if not isinstance(payloads["publish_status"].get("files"), list):
            errors.append("publish_manifest.json: files must be a list")
        for key in ("as_of_date",):
            if key not in payloads["user_models"]:
                errors.append(f"user_model_catalog.json: missing {key}")
            if key not in payloads["recommendation_today"]:
                errors.append(f"user_recommendation_report.json: missing {key}")
            if key not in payloads["performance_summary"]:
                errors.append(f"user_performance_summary.json: missing {key}")
            if key not in payloads["recent_changes"]:
                errors.append(f"user_recent_changes.json: missing {key}")
            if key not in payloads["publish_status"]:
                errors.append(f"publish_manifest.json: missing {key}")
        if "generated_at" not in payloads["recommendation_today"]:
            errors.append("user_recommendation_report.json: missing generated_at")
        if "generated_at" not in payloads["publish_status"]:
            errors.append("publish_manifest.json: missing generated_at")
        if errors:
            raise UserSnapshotLoadError("User snapshot validation failed.", errors=errors)

    def _is_bundle_empty(self, bundle: UserSnapshotBundle) -> bool:
        return not (
            bundle.user_models.get("models")
            and bundle.recommendation_today.get("reports")
            and bundle.performance_summary.get("models")
            and bundle.recent_changes.get("changes")
        )

    def _compute_age_seconds(self, generated_at: str | None) -> int | None:
        parsed = self._parse_iso_datetime(generated_at)
        if parsed is None:
            return None
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return max(int(delta.total_seconds()), 0)

    def _is_age_stale(self, age_seconds: int | None) -> bool:
        if age_seconds is None:
            return False
        return age_seconds > self.settings.snapshot_stale_after_hours * 3600

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
