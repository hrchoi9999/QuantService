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

from service_platform.shared.config import Settings

USER_SNAPSHOT_FILES = {
    "user_models": "user_model_catalog.json",
    "recommendation_today": "user_model_snapshot_report.json",
    "performance_summary": "user_performance_summary.json",
    "recent_changes": "user_recent_changes.json",
    "publish_status": "publish_manifest.json",
}

SERVICE_PROFILE_LABELS = {
    "stable": "안정형",
    "balanced": "균형형",
    "growth": "성장형",
    "auto": "자동전환형",
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
                        "최신 스냅샷을 읽지 못해 이전 정상 데이터를 표시합니다."
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

    def get_publish_status(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.load_bundle(force_refresh=force_refresh).publish_status

    def _load_from_directory(self, directory: Path, *, source_name: str) -> UserSnapshotBundle:
        if not directory.exists():
            raise UserSnapshotLoadError(f"Snapshot directory does not exist: {directory}")

        payloads = {
            key: self._load_json(directory / filename)
            for key, filename in USER_SNAPSHOT_FILES.items()
        }
        payloads = self._sanitize_payloads(payloads)
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
            profile = change.get("service_profile")
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

        return sanitized

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
                item_direction = item.get("direction") or direction
                sanitized.append(
                    {
                        "display_name": display_name,
                        "security_code": security_code,
                        "delta_weight": delta_weight,
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
