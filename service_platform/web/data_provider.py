"""Snapshot loading and caching helpers for the web layer."""

from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from service_platform.publishers.writers.validate_schema import validate_payload
from service_platform.shared.config import Settings
from service_platform.shared.constants import (
    CURRENT_DIRNAME,
    MANIFEST_FILENAME,
    PUBLISHED_DIRNAME,
    SNAPSHOT_FILENAMES,
)

LOGGER = logging.getLogger("quantservice")


class SnapshotLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class SnapshotBundle:
    model_catalog: dict[str, Any]
    daily_recommendations: dict[str, Any]
    recent_changes: dict[str, Any]
    performance_summary: dict[str, Any]
    manifest: dict[str, Any]
    source_name: str
    stale: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def as_of_date(self) -> str | None:
        return self.daily_recommendations.get("as_of_date") or self.manifest.get("as_of_date")

    @property
    def generated_at(self) -> str | None:
        return self.daily_recommendations.get("generated_at") or self.manifest.get("generated_at")


@dataclass
class SnapshotStatus:
    state: str
    source_name: str
    as_of_date: str | None
    generated_at: str | None
    model_count: int
    warnings: list[str]
    errors: list[str]
    files: list[dict[str, Any]]
    cache_ttl_seconds: int
    stale_after_hours: int
    age_seconds: int | None
    latest_published_label: str | None
    last_run_id: str | None
    snapshot_accessible: bool

    @property
    def healthy(self) -> bool:
        return self.state == "healthy"


class SnapshotDataProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_ttl_seconds = max(settings.snapshot_cache_ttl_seconds, 0)
        self._lock = Lock()
        self._cached_bundle: SnapshotBundle | None = None
        self._cache_expires_at = 0.0
        self._last_errors: list[str] = []

    def load_bundle(self, force_refresh: bool = False) -> SnapshotBundle:
        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cached_bundle and now < self._cache_expires_at:
                return deepcopy(self._cached_bundle)

            errors: list[str] = []
            for loader in self._iter_loaders():
                try:
                    bundle = loader()
                    self._cached_bundle = deepcopy(bundle)
                    self._cache_expires_at = now + self.cache_ttl_seconds
                    self._last_errors = []
                    return bundle
                except SnapshotLoadError as exc:
                    errors.extend(exc.errors)
                    LOGGER.warning("message=snapshot_load_failed errors=%s", "; ".join(exc.errors))

            self._last_errors = errors
            if self._cached_bundle is not None:
                stale_bundle = deepcopy(self._cached_bundle)
                stale_bundle.stale = True
                stale_bundle.warnings.extend(
                    ["Showing the last verified snapshot while the latest update is unavailable."]
                )
                stale_bundle.warnings.extend(errors)
                return stale_bundle

            raise SnapshotLoadError(
                "Snapshot data is temporarily unavailable. Please try again shortly.",
                errors=errors,
            )

    def get_status(self, force_refresh: bool = False) -> SnapshotStatus:
        latest_published_label = self._find_latest_published_label(
            self.settings.public_data_dir / PUBLISHED_DIRNAME
        )
        try:
            bundle = self.load_bundle(force_refresh=force_refresh)
            warnings = list(bundle.warnings)
            age_seconds = self._compute_age_seconds(bundle.generated_at)
            is_age_stale = self._is_age_stale(age_seconds)
            if is_age_stale:
                warnings.append(
                    f"Snapshot is older than {self.settings.snapshot_stale_after_hours} hours."
                )
            state = "stale" if bundle.stale or is_age_stale else "healthy"
            errors = self._last_errors if bundle.stale else []
            return SnapshotStatus(
                state=state,
                source_name=bundle.source_name,
                as_of_date=bundle.as_of_date,
                generated_at=bundle.generated_at,
                model_count=len(bundle.model_catalog.get("models", [])),
                warnings=warnings,
                errors=errors,
                files=self._build_file_summaries(bundle),
                cache_ttl_seconds=self.cache_ttl_seconds,
                stale_after_hours=self.settings.snapshot_stale_after_hours,
                age_seconds=age_seconds,
                latest_published_label=latest_published_label,
                last_run_id=bundle.manifest.get("run_id"),
                snapshot_accessible=True,
            )
        except SnapshotLoadError as exc:
            return SnapshotStatus(
                state="unavailable",
                source_name=self.settings.snapshot_source,
                as_of_date=self._cached_bundle.as_of_date if self._cached_bundle else None,
                generated_at=self._cached_bundle.generated_at if self._cached_bundle else None,
                model_count=(
                    len(self._cached_bundle.model_catalog.get("models", []))
                    if self._cached_bundle
                    else 0
                ),
                warnings=[],
                errors=exc.errors,
                files=[],
                cache_ttl_seconds=self.cache_ttl_seconds,
                stale_after_hours=self.settings.snapshot_stale_after_hours,
                age_seconds=self._compute_age_seconds(
                    self._cached_bundle.generated_at if self._cached_bundle else None
                ),
                latest_published_label=latest_published_label,
                last_run_id=(
                    self._cached_bundle.manifest.get("run_id") if self._cached_bundle else None
                ),
                snapshot_accessible=False,
            )

    def _iter_loaders(self):
        if self.settings.snapshot_source == "gcs":
            yield self._load_from_gcs_current
        else:
            yield self._load_from_local_current
            yield self._load_from_local_published

    def _load_from_local_current(self) -> SnapshotBundle:
        current_dir = self.settings.public_data_dir / CURRENT_DIRNAME
        return self._load_from_local_directory(current_dir, "local-current")

    def _load_from_local_published(self) -> SnapshotBundle:
        published_root = self.settings.public_data_dir / PUBLISHED_DIRNAME
        latest_dir = self._find_latest_published_dir(published_root)
        if latest_dir is None:
            raise SnapshotLoadError("No published snapshot fallback is available.")
        return self._load_from_local_directory(latest_dir, "local-published-fallback")

    def _load_from_local_directory(self, directory: Path, source_name: str) -> SnapshotBundle:
        if not directory.exists():
            raise SnapshotLoadError(f"Snapshot directory does not exist: {directory.name}")

        manifest_path = directory / MANIFEST_FILENAME
        manifest = self._load_json_path(manifest_path, required=False) or {}
        payloads = {
            schema_name: self._load_json_path(directory / filename)
            for schema_name, filename in SNAPSHOT_FILENAMES.items()
        }
        self._validate_payloads(payloads)
        return SnapshotBundle(
            model_catalog=payloads["model_catalog"],
            daily_recommendations=payloads["daily_recommendations"],
            recent_changes=payloads["recent_changes"],
            performance_summary=payloads["performance_summary"],
            manifest=manifest,
            source_name=source_name,
        )

    def _load_from_gcs_current(self) -> SnapshotBundle:
        base_url = self._get_gcs_base_url()
        manifest = (
            self._load_json_url(f"{base_url}/current/{MANIFEST_FILENAME}", required=False) or {}
        )
        payloads = {
            schema_name: self._load_json_url(f"{base_url}/current/{filename}")
            for schema_name, filename in SNAPSHOT_FILENAMES.items()
        }
        self._validate_payloads(payloads)
        return SnapshotBundle(
            model_catalog=payloads["model_catalog"],
            daily_recommendations=payloads["daily_recommendations"],
            recent_changes=payloads["recent_changes"],
            performance_summary=payloads["performance_summary"],
            manifest=manifest,
            source_name="gcs-current",
        )

    def _get_gcs_base_url(self) -> str:
        if self.settings.snapshot_gcs_base_url:
            return self.settings.snapshot_gcs_base_url.rstrip("/")
        if self.settings.snapshot_gcs_bucket:
            bucket = self.settings.snapshot_gcs_bucket.strip().removeprefix("gs://")
            return f"https://storage.googleapis.com/{bucket}"
        raise SnapshotLoadError("GCS snapshot source is configured without a bucket or base URL.")

    def _load_json_path(self, path: Path, *, required: bool = True) -> dict[str, Any] | None:
        if not path.exists():
            if required:
                raise SnapshotLoadError(f"Missing snapshot file: {path.name}")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise SnapshotLoadError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

    def _load_json_url(self, url: str, *, required: bool = True) -> dict[str, Any] | None:
        try:
            with urlopen(url, timeout=5) as response:
                payload = response.read().decode("utf-8-sig")
        except URLError as exc:
            if required:
                raise SnapshotLoadError(f"Failed to fetch snapshot from GCS: {url}") from exc
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SnapshotLoadError(f"Invalid JSON fetched from {url}: {exc.msg}") from exc

    def _validate_payloads(self, payloads: dict[str, dict[str, Any]]) -> None:
        validation_errors: list[str] = []
        for schema_name, payload in payloads.items():
            try:
                validate_payload(schema_name, payload)
            except Exception as exc:
                validation_errors.append(f"{schema_name}: {exc}")
        if validation_errors:
            raise SnapshotLoadError("Snapshot validation failed.", errors=validation_errors)

    def _build_file_summaries(self, bundle: SnapshotBundle) -> list[dict[str, Any]]:
        manifest_files = bundle.manifest.get("files") or {}
        summaries = []
        for filename in SNAPSHOT_FILENAMES.values():
            info = manifest_files.get(filename, {})
            summaries.append({"name": filename, "size_bytes": info.get("size_bytes")})
        return summaries

    def _find_latest_published_dir(self, published_root: Path) -> Path | None:
        if not published_root.exists():
            return None

        candidate_days = [path for path in published_root.iterdir() if path.is_dir()]
        for day_dir in sorted(candidate_days, reverse=True):
            run_dirs = [path for path in day_dir.iterdir() if path.is_dir()]
            if run_dirs:
                return sorted(run_dirs, reverse=True)[0]
        return None

    def _find_latest_published_label(self, published_root: Path) -> str | None:
        latest_dir = self._find_latest_published_dir(published_root)
        if latest_dir is None:
            return None
        return latest_dir.relative_to(published_root).as_posix()

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
