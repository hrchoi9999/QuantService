"""Daily publish pipeline helpers."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from service_platform.publishers.adapters import S2Adapter, S2AdapterInput
from service_platform.publishers.adapters.s2_adapter import MODEL_ID as S2_MODEL_ID
from service_platform.publishers.writers.validate_schema import validate_payload
from service_platform.publishers.writers.write_json import describe_json_file, write_json
from service_platform.shared.config import Settings
from service_platform.shared.constants import (
    CURRENT_DIRNAME,
    LOG_DIRNAME,
    MANIFEST_FILENAME,
    PUBLISHED_DIRNAME,
    SNAPSHOT_FILENAMES,
    TMP_DIRNAME,
)
from service_platform.shared.logging import configure_logging

AdapterFactory = Callable[[Settings, date | None], Any]
LOGGER = logging.getLogger("quantservice")


@dataclass(frozen=True)
class PublishResult:
    run_id: str
    asof: str
    current_dir: Path
    published_dir: Path
    manifest_path: Path
    files: dict[str, Path]
    log_path: Path


def build_default_adapter_factories() -> dict[str, AdapterFactory]:
    return {
        S2_MODEL_ID: lambda settings, asof_date: S2Adapter(
            S2AdapterInput(
                holdings_csv=settings.s2_holdings_csv,
                snapshot_csv=settings.s2_snapshot_csv,
                summary_csv=settings.s2_summary_csv,
                asof_date=asof_date,
            )
        )
    }


def _merge_payloads(
    payloads_by_model: list[dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    model_catalog = {"models": []}
    daily = {"as_of_date": None, "generated_at": None, "models": [], "disclaimer": None}
    recent_changes = {"as_of_date": None, "changes": []}
    performance = {"models": []}

    for payloads in payloads_by_model:
        model_catalog["models"].extend(payloads["model_catalog"]["models"])
        daily_payload = payloads["daily_recommendations"]
        daily["as_of_date"] = daily_payload["as_of_date"]
        daily["generated_at"] = daily_payload["generated_at"]
        daily["disclaimer"] = daily_payload["disclaimer"]
        daily["models"].extend(daily_payload["models"])

        changes_payload = payloads["recent_changes"]
        recent_changes["as_of_date"] = changes_payload["as_of_date"]
        recent_changes["changes"].extend(changes_payload["changes"])

        performance["models"].extend(payloads["performance_summary"]["models"])

    return {
        "model_catalog": model_catalog,
        "daily_recommendations": daily,
        "recent_changes": recent_changes,
        "performance_summary": performance,
    }


def _parse_asof(raw_asof: str | None) -> date | None:
    if not raw_asof:
        return None
    return datetime.strptime(raw_asof, "%Y-%m-%d").date()


def _ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _rotate_current(staging_current_dir: Path, current_dir: Path) -> None:
    backup_dir = current_dir.parent / f"{current_dir.name}__backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    try:
        if current_dir.exists():
            current_dir.rename(backup_dir)
        staging_current_dir.rename(current_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if current_dir.exists():
            shutil.rmtree(current_dir)
        if backup_dir.exists():
            backup_dir.rename(current_dir)
        raise


def _cleanup_old_published_dirs(published_root: Path, keep_days: int) -> None:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=keep_days)
    if not published_root.exists():
        return
    for child in published_root.iterdir():
        try:
            child_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if child_date < cutoff and child.is_dir():
            shutil.rmtree(child)


def publish_daily(
    *,
    settings: Settings,
    asof: str | None = None,
    model_ids: list[str] | None = None,
    out_dir: Path | None = None,
    keep_days: int | None = None,
    force: bool = False,
    adapter_factories: dict[str, AdapterFactory] | None = None,
) -> PublishResult:
    asof_date = _parse_asof(asof)
    publish_root = Path(out_dir or settings.publish_root_dir)
    keep_days = keep_days or settings.publish_keep_days
    adapter_factories = adapter_factories or build_default_adapter_factories()
    selected_models = model_ids or list(adapter_factories.keys())

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logs_dir = publish_root / LOG_DIRNAME
    log_path = logs_dir / f"publish_{run_id}.log"
    configure_logging(settings.log_level, log_path)

    LOGGER.info(
        "publish_start",
        extra={"service": "publish", "run_id": run_id, "asof": asof or "latest", "status": "start"},
    )

    payloads_by_model = []
    input_sources: dict[str, dict[str, str]] = {}
    for model_id in selected_models:
        if model_id not in adapter_factories:
            raise ValueError(f"Unsupported model id: {model_id}")
        adapter = adapter_factories[model_id](settings, asof_date)
        payloads = adapter.build_service_payloads()
        payloads_by_model.append(payloads)
        describe_sources = getattr(adapter, "describe_input_sources", lambda: {})
        input_sources[model_id] = describe_sources()

    merged_payloads = _merge_payloads(payloads_by_model)
    for schema_name, payload in merged_payloads.items():
        validate_payload(schema_name, payload)

    effective_asof = merged_payloads["daily_recommendations"]["as_of_date"]
    published_root = publish_root / PUBLISHED_DIRNAME
    version_dir = published_root / effective_asof / run_id
    current_staging_dir = publish_root / TMP_DIRNAME / f"current_{run_id}"
    tmp_run_dir = publish_root / TMP_DIRNAME / run_id
    current_dir = publish_root / CURRENT_DIRNAME

    if version_dir.exists() and not force:
        raise FileExistsError(f"Publish output already exists for run_id={run_id}")

    _ensure_clean_dir(tmp_run_dir)
    _ensure_clean_dir(current_staging_dir)
    version_dir.mkdir(parents=True, exist_ok=True)

    written_files: dict[str, Path] = {}
    for schema_name, filename in SNAPSHOT_FILENAMES.items():
        tmp_file = tmp_run_dir / filename
        current_file = current_staging_dir / filename
        version_file = version_dir / filename
        write_json(tmp_file, merged_payloads[schema_name])
        shutil.copy2(tmp_file, current_file)
        shutil.copy2(tmp_file, version_file)
        written_files[schema_name] = current_file

    manifest = {
        "run_id": run_id,
        "as_of_date": effective_asof,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": selected_models,
        "input_sources": input_sources,
        "files": {
            filename: describe_json_file(version_dir / filename)
            for filename in SNAPSHOT_FILENAMES.values()
        },
    }
    manifest_current = current_staging_dir / MANIFEST_FILENAME
    manifest_version = version_dir / MANIFEST_FILENAME
    write_json(manifest_current, manifest)
    shutil.copy2(manifest_current, manifest_version)

    _rotate_current(current_staging_dir, current_dir)
    shutil.rmtree(tmp_run_dir, ignore_errors=True)
    _cleanup_old_published_dirs(published_root, keep_days)

    LOGGER.info(
        "publish_success",
        extra={"service": "publish", "run_id": run_id, "asof": effective_asof, "status": "ok"},
    )
    return PublishResult(
        run_id=run_id,
        asof=effective_asof,
        current_dir=current_dir,
        published_dir=version_dir,
        manifest_path=current_dir / MANIFEST_FILENAME,
        files=written_files,
        log_path=log_path,
    )
