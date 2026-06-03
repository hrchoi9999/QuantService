from __future__ import annotations

import json
import re
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

USER_SNAPSHOT_FILES = {
    "user_models": "user_model_catalog.json",
    "recommendation_today": "user_model_snapshot_report.json",
    "performance_summary": "user_performance_summary.json",
    "recent_changes": "user_recent_changes.json",
}
USER_SNAPSHOT_OPTIONAL_FILES = {
    "change_history": "user_model_change_history.json",
}
USER_SNAPSHOT_MANIFEST_FILENAMES = (
    "publish_manifest_user.json",
    "publish_manifest.json",
)
REMOTE_SOURCES = {"remote", "http", "gcs"}

SERVICE_PROFILE_LABELS = {
    "stable": "안정형",
    "balanced": "균형형",
    "growth": "성장형",
    "auto": "자동전환형",
}
SERVICE_PROFILE_NAME_ALIASES = {
    "안정형": "stable",
    "안정형 모델": "stable",
    "안정형 퀀트투자 모델": "stable",
    "stable": "stable",
    "균형형": "balanced",
    "균형형 모델": "balanced",
    "균형형 퀀트투자 모델": "balanced",
    "balanced": "balanced",
    "성장형": "growth",
    "성장형 모델": "growth",
    "성장형 퀀트투자 모델": "growth",
    "growth": "growth",
    "자동전환형": "auto",
    "자동전환형 모델": "auto",
    "자동전환형 퀀트투자 모델": "auto",
    "auto": "auto",
}

SERVICE_PROFILE_SUMMARIES = {
    "stable": "채권, 달러, 금 중심으로 낙폭 방어와 안정성을 우선하는 보수형 포트폴리오입니다.",
    "balanced": (
        "배당주와 ETF를 고르게 담아 수익성과 방어력을 함께 추구하는 균형형 포트폴리오입니다."
    ),
    "growth": (
        "성장 업종과 모멘텀 자산에 집중해 수익 기회를 적극적으로 추구하는 성장형 포트폴리오입니다."
    ),
    "auto": (
        "시장 흐름에 따라 안정형과 성장형 사이의 비중을 탄력적으로 조정하는 자동전환 "
        "포트폴리오입니다."
    ),
}

SERVICE_PROFILE_TARGET_USERS = {
    "stable": "변동성을 낮추고 안정적인 자산 배분을 참고하려는 이용자",
    "balanced": "안정성과 수익성의 균형을 함께 참고하려는 이용자",
    "growth": "높은 변동성을 감수하더라도 성장 중심 구성을 참고하려는 이용자",
    "auto": "시장 흐름에 맞춰 자동으로 모델 비중 조정을 참고하려는 이용자",
}

SERVICE_PROFILE_MARKET_VIEWS = {
    "stable": "방어 자산 중심으로 안정성을 우선하는 포지션입니다.",
    "balanced": "배당·지수·가치 자산을 고르게 담아 균형을 유지하는 포지션입니다.",
    "growth": "성장·모멘텀 자산 비중을 높여 수익 기회를 적극적으로 추구하는 포지션입니다.",
    "auto": "시장 국면에 따라 비중을 탄력적으로 조정하는 유연한 포지션입니다.",
}

SERVICE_PROFILE_RATIONALES = {
    "stable": [
        "변동성 완충을 위해 채권과 현금성 자산 비중을 높였습니다.",
        "달러와 금 자산으로 외부 충격에 대한 방어력을 보강했습니다.",
        "주식 비중은 낮게 유지해 급격한 하락 구간의 낙폭을 줄이는 데 초점을 맞췄습니다.",
        "리스크 관리와 안정적인 자산 배분을 우선합니다.",
    ],
    "balanced": [
        "지수 ETF와 배당주를 함께 담아 균형 잡힌 수익 구조를 구성했습니다.",
        "과도한 쏠림을 피하고 업종 분산을 통해 변동성을 완화했습니다.",
        "안정성과 성장성의 균형을 맞추는 데 초점을 두었습니다.",
        "시장 변화에 대응하되 포트폴리오의 중심은 유지합니다.",
    ],
    "growth": [
        "성장 업종과 모멘텀 자산 비중을 높여 수익 기회를 확대했습니다.",
        "실적 개선과 추세 강도가 높은 자산을 중심으로 편입했습니다.",
        "단기 변동성은 감수하되 중장기 성과를 우선합니다.",
        "공격적인 비중 조절로 상승 구간의 탄력을 노립니다.",
    ],
    "auto": [
        "시장 국면 변화에 따라 방어 자산과 성장 자산의 비중을 자동으로 조정합니다.",
        "과도한 방향성 베팅을 줄이고 상황 대응력을 높였습니다.",
        "한 가지 스타일에 고정되지 않고 유연하게 자산을 재배치합니다.",
        "시장 변화에 민감하게 대응하는 동적 포트폴리오입니다.",
    ],
}

SERVICE_PROFILE_RISK_LEVELS = {
    "stable": "낮음",
    "balanced": "보통",
    "growth": "높음",
    "auto": "중간",
}

SERVICE_PROFILE_CHANGE_REASONS = {
    "stable": "시장 변동성에 대비해 방어 자산과 완충 자산의 비중을 조정했습니다.",
    "balanced": "균형 유지를 위해 상대 강도가 높은 자산을 늘리고 약한 자산을 줄였습니다.",
    "growth": "성과와 추세를 반영해 성장 자산 중심으로 비중을 재조정했습니다.",
    "auto": "시장 국면 변화에 맞춰 모델 비중을 자동으로 재조정했습니다.",
}

DEFAULT_DISCLAIMER = (
    "이 자료는 공개 규칙 기반 모델 정보와 백테스트 결과를 설명하기 위한 참고자료이며 "
    "특정 개인에 대한 투자자문이나 실제 매매 지시가 아닙니다."
)
GARBLED_MARKERS = ("??", "챙", "혮", "湲", "�", "ì", "í", "ê", "좎", "쒖")


class UserSnapshotLoadError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


def _normalized_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class UserSnapshotBundle:
    user_models: dict[str, Any]
    recommendation_today: dict[str, Any]
    performance_summary: dict[str, Any]
    recent_changes: dict[str, Any]
    change_history: dict[str, Any]
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
                return self._cached_bundle

            try:
                bundle = self._load_bundle_with_fallbacks()
            except UserSnapshotLoadError as exc:
                self._last_errors = exc.errors
                if self._cached_bundle is not None:
                    stale_bundle = deepcopy(self._cached_bundle)
                    stale_bundle.stale = True
                    stale_bundle.warnings = list(stale_bundle.warnings) + [
                        "최신 스냅샷을 읽지 못해 이전 정상 데이터를 표시합니다."
                    ]
                    stale_bundle.errors = exc.errors
                    return stale_bundle
                raise

            self._cached_bundle = bundle
            self._cache_expires_at = now + self.cache_ttl_seconds
            self._last_errors = list(bundle.errors)
            return bundle

    def get_status(self, force_refresh: bool = False) -> UserSnapshotStatus:
        try:
            bundle = self.load_bundle(force_refresh=force_refresh)
        except UserSnapshotLoadError as exc:
            return UserSnapshotStatus(
                state="error",
                source_name=self._configured_source_name(),
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
            warnings.append("사용 가능한 사용자 스냅샷 데이터가 아직 없습니다.")
        elif bundle.stale or self._is_age_stale(age_seconds):
            state = "stale"
            if self._is_age_stale(age_seconds):
                warnings.append(
                    "스냅샷 생성 시각이 "
                    f"{self.settings.snapshot_stale_after_hours}시간을 넘어 오래되었습니다."
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

    def get_model_snapshots_today(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).recommendation_today

    def get_model_snapshot_by_profile(
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

    def get_recommendation_today(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.get_model_snapshots_today(force_refresh=force_refresh)

    def get_recommendation_by_profile(
        self, service_profile: str, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        return self.get_model_snapshot_by_profile(
            service_profile,
            force_refresh=force_refresh,
        )

    def get_performance_summary(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).performance_summary

    def get_recent_changes(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).recent_changes

    def get_change_history(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).change_history

    def get_publish_status(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).publish_status

    def _load_bundle_with_fallbacks(self) -> UserSnapshotBundle:
        errors: list[str] = []
        for loader in self._iter_loaders():
            try:
                bundle = loader()
            except UserSnapshotLoadError as exc:
                errors.extend(exc.errors)
                continue

            if errors:
                bundle.errors = list(bundle.errors) + errors
                if bundle.source_name == "snapshot-local":
                    bundle.warnings = list(bundle.warnings) + [
                        "원격 사용자 스냅샷을 읽지 못해 로컬 current 데이터를 사용합니다."
                    ]
            return bundle

        raise UserSnapshotLoadError(
            "User snapshot handoff is temporarily unavailable.",
            errors=errors,
        )

    def _iter_loaders(self):
        use_remote = self.settings.snapshot_source in REMOTE_SOURCES or bool(
            self.settings.snapshot_gcs_base_url
        )
        if use_remote:
            yield self._load_from_remote_current
        yield self._load_from_local_current

    def _load_from_local_current(self) -> UserSnapshotBundle:
        return self._load_from_directory(self.root_dir, source_name="snapshot-local")

    def _load_from_remote_current(self) -> UserSnapshotBundle:
        base_url = self._get_remote_base_url()
        request_token = str(int(time.time()))
        payloads = {
            key: self._load_json_url(
                self._with_cache_buster(f"{base_url}/{filename}", request_token)
            )
            for key, filename in USER_SNAPSHOT_FILES.items()
        }
        payloads.update(
            {
                key: payload
                for key, filename in USER_SNAPSHOT_OPTIONAL_FILES.items()
                if (
                    payload := self._load_json_url(
                        self._with_cache_buster(f"{base_url}/{filename}", request_token),
                        required=False,
                    )
                )
                is not None
            }
        )
        manifest, manifest_warnings = self._load_manifest_from_remote(base_url, request_token)
        warnings = list(manifest_warnings)
        if manifest is None:
            manifest = self._build_synthetic_manifest(payloads)
            warnings.append(
                "원격 current manifest를 찾지 못해 payload 기준으로 메타데이터를 구성했습니다."
            )
        return self._build_bundle_from_payloads(
            payloads,
            manifest,
            source_name="snapshot-remote",
            warnings=warnings,
        )

    def _load_from_directory(self, directory: Path, *, source_name: str) -> UserSnapshotBundle:
        if not directory.exists():
            raise UserSnapshotLoadError(f"Snapshot directory does not exist: {directory}")

        payloads = {
            key: self._load_json(directory / filename)
            for key, filename in USER_SNAPSHOT_FILES.items()
        }
        for key, filename in USER_SNAPSHOT_OPTIONAL_FILES.items():
            path = directory / filename
            if path.exists():
                payloads[key] = self._load_json(path)
        manifest, manifest_warnings = self._load_manifest_from_directory(directory)
        warnings = list(manifest_warnings)
        if manifest is None:
            manifest = self._build_synthetic_manifest(payloads)
            warnings.append(
                "current manifest를 찾지 못해 payload 기준으로 메타데이터를 구성했습니다."
            )
        return self._build_bundle_from_payloads(
            payloads,
            manifest,
            source_name=source_name,
            warnings=warnings,
        )

    def _build_bundle_from_payloads(
        self,
        payloads: dict[str, dict[str, Any]],
        manifest: dict[str, Any],
        *,
        source_name: str,
        warnings: list[str] | None = None,
    ) -> UserSnapshotBundle:
        combined_payloads = dict(payloads)
        combined_payloads["change_history"] = self._normalize_change_history_payload(
            combined_payloads.get("change_history"),
            combined_payloads["recent_changes"],
        )
        combined_payloads["recent_changes"] = self._fill_recent_changes_from_history(
            combined_payloads["recent_changes"],
            combined_payloads["change_history"],
        )
        combined_payloads["publish_status"] = manifest
        combined_payloads = self._sanitize_payloads(combined_payloads)
        self._validate_payloads(combined_payloads)
        bundle = UserSnapshotBundle(
            user_models=combined_payloads["user_models"],
            recommendation_today=combined_payloads["recommendation_today"],
            performance_summary=combined_payloads["performance_summary"],
            recent_changes=combined_payloads["recent_changes"],
            change_history=combined_payloads["change_history"],
            publish_status=combined_payloads["publish_status"],
            source_name=source_name,
            warnings=list(warnings or []),
        )
        bundle.empty = self._is_bundle_empty(bundle)
        self._validate_bundle_consistency(bundle)
        return bundle

    def _load_manifest_from_directory(
        self, directory: Path
    ) -> tuple[dict[str, Any] | None, list[str]]:
        warnings: list[str] = []
        for filename in USER_SNAPSHOT_MANIFEST_FILENAMES:
            path = directory / filename
            if not path.exists():
                continue
            try:
                return self._load_json(path), warnings
            except UserSnapshotLoadError as exc:
                warnings.extend(exc.errors)
        return None, warnings

    def _load_manifest_from_remote(
        self, base_url: str, request_token: str
    ) -> tuple[dict[str, Any] | None, list[str]]:
        warnings: list[str] = []
        for filename in USER_SNAPSHOT_MANIFEST_FILENAMES:
            url = self._with_cache_buster(f"{base_url}/{filename}", request_token)
            try:
                payload = self._load_json_url(url, required=False)
            except UserSnapshotLoadError as exc:
                warnings.extend(exc.errors)
                continue
            if payload is not None:
                return payload, warnings
        return None, warnings

    def _build_synthetic_manifest(self, payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
        recommendation = payloads.get("recommendation_today") or {}
        as_of_date = _normalized_value(recommendation.get("as_of_date"))
        if as_of_date is None:
            for payload in payloads.values():
                as_of_date = _normalized_value(payload.get("as_of_date"))
                if as_of_date:
                    break
        return {
            "as_of_date": as_of_date,
            "generated_at": _normalized_value(recommendation.get("generated_at")),
            "files": list(USER_SNAPSHOT_FILES.values()),
            "channel": "user-facing",
            "version": "synthetic-current-manifest",
        }

    def _normalize_change_history_payload(
        self,
        history_payload: dict[str, Any] | None,
        recent_changes: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(history_payload, dict):
            weekly_rows = self._normalize_change_period_rows(
                history_payload.get("weekly"),
                recent_changes,
                period_type="weekly",
            )
            monthly_rows = self._normalize_change_period_rows(
                history_payload.get("monthly"),
                recent_changes,
                period_type="monthly",
            )
            history_rows = history_payload.get("history")
            if history_rows is None:
                history_rows = history_payload.get("items")
            if isinstance(history_rows, list):
                normalized_rows = [
                    self._normalize_change_history_row(row, recent_changes)
                    for row in history_rows
                    if isinstance(row, dict)
                ]
                return {
                    **history_payload,
                    "as_of_date": history_payload.get("as_of_date")
                    or recent_changes.get("as_of_date"),
                    "weekly": weekly_rows,
                    "monthly": monthly_rows,
                    "history": normalized_rows,
                }
            if weekly_rows or monthly_rows:
                return {
                    **history_payload,
                    "as_of_date": history_payload.get("as_of_date")
                    or recent_changes.get("as_of_date"),
                    "weekly": weekly_rows,
                    "monthly": monthly_rows,
                    "history": [
                        {
                            "change_date": row.get("period_key") or row.get("as_of_date"),
                            "summary": "주간 공개 모델 변경내역",
                            "changes": list(row.get("models") or []),
                        }
                        for row in weekly_rows
                    ],
                }
        return self._build_change_history_from_recent(recent_changes)

    def _normalize_change_period_rows(
        self,
        rows: Any,
        recent_changes: dict[str, Any],
        *,
        period_type: str,
    ) -> list[dict[str, Any]]:
        normalized_rows: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return normalized_rows
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = dict(row)
            normalized["period_type"] = (
                _normalized_value(normalized.get("period_type")) or period_type
            )
            normalized["period_key"] = (
                _normalized_value(normalized.get("period_key"))
                or _normalized_value(normalized.get("as_of_date"))
                or _normalized_value(normalized.get("end_date"))
                or _normalized_value(recent_changes.get("as_of_date"))
            )
            models = normalized.get("models")
            normalized["models"] = models if isinstance(models, list) else []
            normalized_rows.append(normalized)
        return normalized_rows

    def _fill_recent_changes_from_history(
        self,
        recent_changes: dict[str, Any],
        history_payload: dict[str, Any],
    ) -> dict[str, Any]:
        changes = recent_changes.get("changes") if isinstance(recent_changes, dict) else None
        if changes:
            return recent_changes
        weekly_rows = history_payload.get("weekly") if isinstance(history_payload, dict) else None
        if not isinstance(weekly_rows, list) or not weekly_rows:
            return recent_changes
        latest = weekly_rows[0] if isinstance(weekly_rows[0], dict) else {}
        latest_models = latest.get("models") if isinstance(latest, dict) else []
        if not isinstance(latest_models, list) or not latest_models:
            return recent_changes
        filled = dict(recent_changes)
        filled["as_of_date"] = (
            filled.get("as_of_date")
            or latest.get("as_of_date")
            or latest.get("period_key")
            or history_payload.get("as_of_date")
        )
        filled["changes"] = list(latest_models)
        filled["source"] = "change_history_latest_weekly_fallback"
        return filled

    def _build_change_history_from_recent(self, recent_changes: dict[str, Any]) -> dict[str, Any]:
        as_of_date = _normalized_value(recent_changes.get("as_of_date"))
        changes = recent_changes.get("changes") if isinstance(recent_changes, dict) else []
        history_rows = (
            [
                {
                    "change_date": as_of_date,
                    "summary": "최신 공개 모델 변경내역",
                    "changes": list(changes or []),
                }
            ]
            if changes
            else []
        )
        weekly_rows = (
            [
                {
                    "period_type": "weekly",
                    "period_key": as_of_date,
                    "as_of_date": as_of_date,
                    "models": list(changes or []),
                }
            ]
            if changes
            else []
        )
        return {
            "as_of_date": as_of_date,
            "source": "recent_changes_fallback",
            "weekly": weekly_rows,
            "monthly": [],
            "history": history_rows,
        }

    def _normalize_change_history_row(
        self,
        row: dict[str, Any],
        recent_changes: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(row)
        change_date = (
            _normalized_value(normalized.get("change_date"))
            or _normalized_value(normalized.get("as_of_date"))
            or _normalized_value(normalized.get("date"))
            or _normalized_value(recent_changes.get("as_of_date"))
        )
        normalized["change_date"] = change_date
        changes = normalized.get("changes")
        if changes is None:
            changes = normalized.get("items")
        normalized["changes"] = changes if isinstance(changes, list) else []
        return normalized

    def _validate_bundle_consistency(self, bundle: UserSnapshotBundle) -> None:
        manifest_as_of = _normalized_value(bundle.publish_status.get("as_of_date"))
        payload_pairs = [
            ("user_model_catalog.json", bundle.user_models),
            ("user_model_snapshot_report.json", bundle.recommendation_today),
            ("user_performance_summary.json", bundle.performance_summary),
            ("user_recent_changes.json", bundle.recent_changes),
        ]
        payload_as_ofs = [
            _normalized_value(payload.get("as_of_date"))
            for _, payload in payload_pairs
            if _normalized_value(payload.get("as_of_date"))
        ]
        canonical_as_of = manifest_as_of or (payload_as_ofs[0] if payload_as_ofs else None)
        mismatches: list[str] = []
        for filename, payload in payload_pairs:
            payload_as_of = _normalized_value(payload.get("as_of_date"))
            if canonical_as_of and payload_as_of and payload_as_of != canonical_as_of:
                mismatches.append(f"{filename}={payload_as_of}")
        if mismatches:
            details = ", ".join(mismatches)
            raise UserSnapshotLoadError(
                "User snapshot handoff files are out of sync.",
                errors=[
                    (
                        "사용자 snapshot handoff 파일의 기준일이 서로 다릅니다: "
                        f"manifest={canonical_as_of}, {details}"
                    )
                ],
            )

        manifest_generated_at = _normalized_value(bundle.publish_status.get("generated_at"))
        report_generated_at = _normalized_value(bundle.recommendation_today.get("generated_at"))
        if (
            manifest_generated_at
            and report_generated_at
            and manifest_generated_at != report_generated_at
        ):
            raise UserSnapshotLoadError(
                "User snapshot handoff generated_at values are out of sync.",
                errors=[
                    (
                        "사용자 snapshot manifest와 report generated_at이 다릅니다: "
                        f"manifest={manifest_generated_at}, report={report_generated_at}"
                    )
                ],
            )

    def _get_remote_base_url(self) -> str:
        base_url = self.settings.snapshot_gcs_base_url.strip().rstrip("/")
        if base_url:
            return base_url
        if self.settings.snapshot_gcs_bucket:
            bucket = self.settings.snapshot_gcs_bucket.strip().removeprefix("gs://")
            return f"https://storage.googleapis.com/{bucket}/current"
        raise UserSnapshotLoadError(
            "Remote user snapshot source is configured without SNAPSHOT_GCS_BASE_URL or bucket."
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

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise UserSnapshotLoadError(f"Missing snapshot file: {path.name}")
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise UserSnapshotLoadError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

    @staticmethod
    def _load_json_url(url: str, *, required: bool = True) -> dict[str, Any] | None:
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
            with urlopen(request_target, timeout=5) as response:
                payload = response.read().decode("utf-8-sig")
        except (OSError, URLError) as exc:
            if required:
                raise UserSnapshotLoadError(
                    f"Failed to fetch user snapshot handoff: {url}"
                ) from exc
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise UserSnapshotLoadError(f"Invalid JSON fetched from {url}: {exc.msg}") from exc

    def _configured_source_name(self) -> str:
        use_remote = self.settings.snapshot_source in REMOTE_SOURCES or bool(
            self.settings.snapshot_gcs_base_url
        )
        return "snapshot-remote" if use_remote else "snapshot-local"

    def _sanitize_payloads(self, payloads: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        sanitized = deepcopy(payloads)
        recommendation = sanitized["recommendation_today"]
        current_market_regime = recommendation.get("current_market_regime")

        for model in sanitized["user_models"].get("models", []):
            profile = model.get("service_profile")
            model["user_model_name"] = self._sanitize_model_name(
                model.get("user_model_name"), profile
            )
            model["summary"] = self._sanitize_profile_summary(model.get("summary"), profile)
            reference_usage_context = self._sanitize_target_user_type(
                model.get("reference_usage_context") or model.get("target_user_type"),
                profile,
            )
            model["reference_usage_context"] = reference_usage_context
            model.pop("target_user_type", None)
            compliance_metadata = model.get("compliance_metadata") or {}
            compliance_metadata["is_personalized_advice"] = False
            model["compliance_metadata"] = compliance_metadata

        for report in recommendation.get("reports", []):
            profile = report.get("service_profile")
            report["user_model_name"] = self._sanitize_model_name(
                report.get("user_model_name"), profile
            )
            report["summary_text"] = self._sanitize_profile_summary(
                report.get("summary_text"), profile
            )
            report["market_view"] = self._sanitize_market_view(
                report.get("market_view"), profile, current_market_regime
            )
            report["risk_level"] = self._sanitize_risk_level(report.get("risk_level"), profile)
            report["rationale_items"] = self._sanitize_rationales(
                report.get("rationale_items"), profile
            )
            report["disclaimer_text"] = self._sanitize_disclaimer(report.get("disclaimer_text"))
            report.pop("target_user_type", None)
            compliance_metadata = report.get("compliance_metadata") or {}
            compliance_metadata["is_personalized_advice"] = False
            report["compliance_metadata"] = compliance_metadata
            for item in report.get("allocation_items", []):
                item["display_name"] = self._sanitize_display_name(
                    item.get("display_name"), item.get("asset_group")
                )
                item["role_summary"] = self._sanitize_role_summary(
                    item.get("role_summary"),
                    item.get("asset_group"),
                    item.get("source_type"),
                    item.get("display_name"),
                )
            change_log = report.get("change_log") or {}
            increase_items = self._sanitize_change_items(
                change_log.get("increase_items") or change_log.get("increased_assets"),
                direction="increase",
            )
            decrease_items = self._sanitize_change_items(
                change_log.get("decrease_items") or change_log.get("decreased_assets"),
                direction="decrease",
            )
            change_log["increase_items"] = increase_items
            change_log["decrease_items"] = decrease_items
            change_log["increased_assets"] = increase_items
            change_log["decreased_assets"] = decrease_items
            change_log["change_reason"] = self._sanitize_change_reason(
                change_log.get("change_reason"), profile
            )
            report["change_log"] = change_log

        for model in sanitized["performance_summary"].get("models", []):
            profile = model.get("service_profile")
            model["user_model_name"] = self._sanitize_model_name(
                model.get("user_model_name"), profile
            )
            model["note"] = self._sanitize_profile_summary(model.get("note"), profile)
            compliance_metadata = model.get("compliance_metadata") or {}
            compliance_metadata["is_personalized_advice"] = False
            model["compliance_metadata"] = compliance_metadata

        for change in sanitized["recent_changes"].get("changes", []):
            self._sanitize_recent_change(change)

        sanitized_change_ids: set[int] = set()
        for period_key in ("weekly", "monthly"):
            for period_row in sanitized["change_history"].get(period_key, []):
                period_models = period_row.get("models")
                if not isinstance(period_models, list):
                    period_row["models"] = []
                    continue
                for change in period_models:
                    if isinstance(change, dict):
                        self._sanitize_recent_change_once(change, sanitized_change_ids)

        for history_row in sanitized["change_history"].get("history", []):
            history_changes = history_row.get("changes")
            if not isinstance(history_changes, list):
                history_row["changes"] = []
                continue
            for change in history_changes:
                if isinstance(change, dict):
                    self._sanitize_recent_change_once(change, sanitized_change_ids)

        return sanitized

    def _sanitize_recent_change_once(
        self,
        change: dict[str, Any],
        sanitized_change_ids: set[int],
    ) -> None:
        change_id = id(change)
        if change_id in sanitized_change_ids:
            return
        sanitized_change_ids.add(change_id)
        self._sanitize_recent_change(change)

    def _sanitize_recent_change(self, change: dict[str, Any]) -> None:
        profile = self._resolve_service_profile(change)
        if profile:
            change["service_profile"] = profile
        change["user_model_name"] = self._sanitize_model_name(
            change.get("user_model_name"), profile
        )
        change["summary"] = self._sanitize_profile_summary(change.get("summary"), profile)
        change["increase_items"] = self._sanitize_change_items(
            change.get("increase_items") or change.get("increased_assets"),
            direction="increase",
        )
        change["decrease_items"] = self._sanitize_change_items(
            change.get("decrease_items") or change.get("decreased_assets"),
            direction="decrease",
        )
        change["reason_text"] = self._sanitize_change_reason(change.get("reason_text"), profile)
        compliance_metadata = change.get("compliance_metadata") or {}
        compliance_metadata["is_personalized_advice"] = False
        change["compliance_metadata"] = compliance_metadata

    def _resolve_service_profile(self, row: dict[str, Any]) -> str:
        direct_profile = str(row.get("service_profile") or "").strip().lower()
        if direct_profile in SERVICE_PROFILE_LABELS:
            return direct_profile
        metadata = row.get("model_metadata") if isinstance(row.get("model_metadata"), dict) else {}
        metadata_profile = (
            str(
                metadata.get("service_profile")
                or metadata.get("profile")
                or metadata.get("profile_code")
                or ""
            )
            .strip()
            .lower()
        )
        if metadata_profile in SERVICE_PROFILE_LABELS:
            return metadata_profile
        candidates = [
            row.get("user_model_name"),
            row.get("quant_model_name"),
            row.get("change_subject_name"),
            metadata.get("model_display_name"),
            metadata.get("change_subject_name"),
            metadata.get("performance_subject_name"),
        ]
        for candidate in candidates:
            repaired = self._repair_text(candidate)
            if repaired in SERVICE_PROFILE_NAME_ALIASES:
                return SERVICE_PROFILE_NAME_ALIASES[repaired]
            compact = repaired.replace(" ", "")
            if compact in SERVICE_PROFILE_NAME_ALIASES:
                return SERVICE_PROFILE_NAME_ALIASES[compact]
            if "안정형" in repaired:
                return "stable"
            if "균형형" in repaired:
                return "balanced"
            if "성장형" in repaired:
                return "growth"
            if "자동전환형" in repaired:
                return "auto"
        return ""

    def _sanitize_model_name(self, value: Any, profile: str | None) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return SERVICE_PROFILE_LABELS.get(profile or "", repaired or "퀀트투자 모델")

    def _sanitize_profile_summary(self, value: Any, profile: str | None) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return SERVICE_PROFILE_SUMMARIES.get(
            profile or "", "현재 시장 상황에 맞춘 퀀트투자 모델 요약입니다."
        )

    def _sanitize_target_user_type(self, value: Any, profile: str | None) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return SERVICE_PROFILE_TARGET_USERS.get(profile or "", "이 모델 정보를 참고하려는 이용자")

    def _sanitize_market_view(
        self, value: Any, profile: str | None, current_market_regime: str | None
    ) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        regime_suffix = {
            "bull": "강세 국면",
            "bear": "약세 국면",
            "sideways": "횡보 국면",
            "neutral": "중립 국면",
        }.get(current_market_regime or "", None)
        base = SERVICE_PROFILE_MARKET_VIEWS.get(profile or "", "현재 시장에 대응하는 포지션입니다.")
        if regime_suffix and regime_suffix not in base:
            return f"{base} 현재 시장은 {regime_suffix}으로 판단합니다."
        return base

    def _sanitize_risk_level(self, value: Any, profile: str | None) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return SERVICE_PROFILE_RISK_LEVELS.get(profile or "", "보통")

    def _sanitize_rationales(self, values: Any, profile: str | None) -> list[str]:
        if isinstance(values, list):
            repaired_values = [self._repair_text(item) for item in values]
            if repaired_values and any(
                item and not self._looks_garbled(item) for item in repaired_values
            ):
                return [item for item in repaired_values if item]
        return list(SERVICE_PROFILE_RATIONALES.get(profile or "", []))

    def _sanitize_disclaimer(self, value: Any) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return DEFAULT_DISCLAIMER

    def _sanitize_display_name(self, value: Any, asset_group: str | None) -> str:
        repaired = self._repair_text(value)
        if asset_group == "cash":
            return "현금/대기자금"
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return repaired or "종목명 미확인"

    def _sanitize_role_summary(
        self, value: Any, asset_group: str | None, source_type: str | None, display_name: str | None
    ) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        name = display_name or ""
        if asset_group == "cash":
            return "유동성 및 대기 자금"
        if "금" in name:
            return "금 자산 분산 투자"
        if "달러" in name:
            return "달러 헤지 자산"
        if "국채" in name or "채" in name:
            return "채권형 완충 자산"
        if "인버스" in name:
            return "하락 방어용 헤지 자산"
        if source_type == "ETF" or asset_group == "etf":
            return "ETF 분산 투자"
        return "핵심 편입 자산"

    def _sanitize_change_items(self, values: Any, direction: str) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        sanitized: list[dict[str, Any]] = []
        for item in values:
            if isinstance(item, dict):
                display_name = self._sanitize_display_name(item.get("display_name"), None)
                security_code = item.get("security_code")
                if security_code is not None:
                    security_code = str(security_code)
                delta_weight = item.get("delta_weight")
                if not isinstance(delta_weight, (int, float)):
                    delta_weight = None
                latest_delta_weight = item.get("latest_delta_weight")
                if not isinstance(latest_delta_weight, (int, float)):
                    latest_delta_weight = None
                source_dates = item.get("source_dates")
                if not isinstance(source_dates, list):
                    source_dates = []
                occurrence_count = item.get("occurrence_count")
                if not isinstance(occurrence_count, int):
                    occurrence_count = None
                item_direction = item.get("direction") or direction
                sanitized.append(
                    {
                        "display_name": display_name,
                        "security_code": security_code,
                        "delta_weight": delta_weight,
                        "latest_delta_weight": latest_delta_weight,
                        "source_dates": source_dates,
                        "occurrence_count": occurrence_count,
                        "direction": item_direction,
                    }
                )
                continue

            repaired = self._repair_text(item)
            repaired = re.sub(r"\s{2,}", " ", repaired).strip()
            if not repaired:
                continue
            sanitized.append(
                {
                    "display_name": repaired,
                    "security_code": None,
                    "delta_weight": None,
                    "direction": direction,
                }
            )
        return sanitized

    def _sanitize_change_reason(self, value: Any, profile: str | None) -> str:
        repaired = self._repair_text(value)
        if repaired and not self._looks_garbled(repaired):
            return repaired
        return SERVICE_PROFILE_CHANGE_REASONS.get(
            profile or "", "시장 변화에 따라 포트폴리오 비중을 재조정했습니다."
        )

    def _repair_text(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        repaired = value.strip()
        if not repaired:
            return repaired
        candidate = self._try_utf8_repair(repaired)
        if self._text_score(candidate) > self._text_score(repaired):
            repaired = candidate
        return repaired

    def _try_utf8_repair(self, value: str) -> str:
        try:
            return value.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

    def _looks_garbled(self, value: str) -> bool:
        if not value:
            return False
        return any(marker in value for marker in GARBLED_MARKERS)

    def _text_score(self, value: str) -> int:
        hangul_count = sum(1 for ch in value if "\uac00" <= ch <= "\ud7a3")
        ascii_letters = sum(1 for ch in value if ch.isascii() and ch.isalpha())
        garbled_penalty = sum(value.count(marker) for marker in GARBLED_MARKERS)
        return (hangul_count * 3) + ascii_letters - (garbled_penalty * 4)

    def _validate_payloads(self, payloads: dict[str, dict[str, Any]]) -> None:
        errors: list[str] = []
        if not isinstance(payloads["user_models"].get("models"), list):
            errors.append("user_model_catalog.json: models must be a list")
        if not isinstance(payloads["recommendation_today"].get("reports"), list):
            errors.append("user_model_snapshot_report.json: reports must be a list")
        if not isinstance(payloads["performance_summary"].get("models"), list):
            errors.append("user_performance_summary.json: models must be a list")
        if not isinstance(payloads["recent_changes"].get("changes"), list):
            errors.append("user_recent_changes.json: changes must be a list")
        if not isinstance(payloads["change_history"].get("history"), list):
            errors.append("user_model_change_history.json: history must be a list")
        if not isinstance(payloads["change_history"].get("weekly"), list):
            errors.append("user_model_change_history.json: weekly must be a list")
        if not isinstance(payloads["change_history"].get("monthly"), list):
            errors.append("user_model_change_history.json: monthly must be a list")
        if not isinstance(payloads["publish_status"].get("files"), list):
            errors.append("publish_manifest.json: files must be a list")
        for key in ("as_of_date",):
            if key not in payloads["user_models"]:
                errors.append(f"user_model_catalog.json: missing {key}")
            if key not in payloads["recommendation_today"]:
                errors.append(f"user_model_snapshot_report.json: missing {key}")
            if key not in payloads["performance_summary"]:
                errors.append(f"user_performance_summary.json: missing {key}")
            if key not in payloads["recent_changes"]:
                errors.append(f"user_recent_changes.json: missing {key}")
            if key not in payloads["publish_status"]:
                errors.append(f"publish_manifest.json: missing {key}")
        if "generated_at" not in payloads["recommendation_today"]:
            errors.append("user_model_snapshot_report.json: missing generated_at")
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
