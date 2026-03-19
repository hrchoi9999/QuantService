import json
from pathlib import Path

from service_platform.shared.config import Settings
from service_platform.web.data_provider import SnapshotDataProvider

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "service_platform" / "schemas" / "examples"
EXAMPLE_FILES = {
    "model_catalog": EXAMPLE_DIR / "model_catalog.example.json",
    "daily_recommendations": EXAMPLE_DIR / "daily_recommendations.example.json",
    "recent_changes": EXAMPLE_DIR / "recent_changes.example.json",
    "performance_summary": EXAMPLE_DIR / "performance_summary.example.json",
}


def build_settings(tmp_path: Path, ttl_seconds: int = 60, stale_after_hours: int = 24) -> Settings:
    public_data_dir = tmp_path / "public_data"
    return Settings(
        app_env="test",
        web_host="127.0.0.1",
        web_port=8000,
        session_secret_key="test-secret",
        public_data_dir=public_data_dir,
        publish_root_dir=public_data_dir,
        feedback_db_path=tmp_path / "feedback.db",
        app_db_path=tmp_path / "app.db",
        backup_dir=tmp_path / "backups",
        alert_log_path=tmp_path / "alerts.log",
        alert_webhook_url="",
        alert_throttle_seconds=10,
        log_level="INFO",
        publish_keep_days=14,
        snapshot_source="local",
        snapshot_cache_ttl_seconds=ttl_seconds,
        snapshot_stale_after_hours=stale_after_hours,
        snapshot_gcs_bucket="",
        snapshot_gcs_base_url="",
        feedback_rate_limit_seconds=60,
        feedback_duplicate_window_seconds=3600,
        feedback_message_min_length=10,
        feedback_admin_key="secret-key",
        analytics_window_hours=24,
        trial_mode=True,
        trial_default_plan="starter",
        trial_end_date="2026-06-11",
        trial_applies_to="authenticated_only",
        allow_higher_plan_during_trial=True,
        billing_enabled=False,
        billing_mode="test",
        billing_cycle_days=30,
        billing_currency="KRW",
        lightpay_mid="test-mid",
        lightpay_merchant_key="test-merchant-key",
        lightpay_return_url="http://127.0.0.1:8000/billing/return",
        lightpay_notify_url="http://127.0.0.1:8000/billing/notify",
        lightpay_notify_allowed_ips=(),
        phone_verification_mode="mock",
        phone_verification_code_ttl_seconds=300,
        phone_verification_preview_enabled=True,
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
    )


def seed_snapshot(target_dir: Path, generated_at: str = "2026-03-19T12:00:00Z") -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, source in EXAMPLE_FILES.items():
        output_name = f"{filename}.json"
        target_dir.joinpath(output_name).write_text(
            source.read_text(encoding="utf-8-sig"),
            encoding="utf-8-sig",
        )

    daily = json.loads((EXAMPLE_FILES["daily_recommendations"]).read_text(encoding="utf-8-sig"))
    daily["generated_at"] = generated_at
    target_dir.joinpath("daily_recommendations.json").write_text(
        json.dumps(daily, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )

    manifest = {
        "run_id": "test-run",
        "as_of_date": "2026-03-10",
        "generated_at": generated_at,
        "models": ["quality_momentum_kr", "value_recovery_kr"],
        "files": {
            "model_catalog.json": {"size_bytes": 100},
            "daily_recommendations.json": {"size_bytes": 200},
            "recent_changes.json": {"size_bytes": 300},
            "performance_summary.json": {"size_bytes": 150},
        },
    }
    target_dir.joinpath("publish_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )


def test_provider_loads_current_snapshot_and_reports_status(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_snapshot(settings.public_data_dir / "current")

    provider = SnapshotDataProvider(settings)
    bundle = provider.load_bundle()
    status = provider.get_status()

    assert bundle.as_of_date == "2026-03-10"
    assert bundle.source_name == "local-current"
    assert status.state == "healthy"
    assert status.model_count == 2
    assert status.snapshot_accessible is True
    assert status.last_run_id == "test-run"


def test_provider_falls_back_to_latest_published_snapshot(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_snapshot(settings.public_data_dir / "published" / "2026-03-10" / "20260310T081000Z")

    provider = SnapshotDataProvider(settings)
    bundle = provider.load_bundle()

    assert bundle.source_name == "local-published-fallback"
    assert bundle.as_of_date == "2026-03-10"


def test_provider_marks_snapshot_stale_when_generated_at_is_old(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, stale_after_hours=1)
    seed_snapshot(settings.public_data_dir / "current", generated_at="2025-03-10T08:10:00Z")

    provider = SnapshotDataProvider(settings)
    status = provider.get_status()

    assert status.state == "stale"
    assert status.age_seconds is not None
    assert status.warnings


def test_provider_returns_stale_cache_when_current_snapshot_breaks(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, ttl_seconds=0)
    current_dir = settings.public_data_dir / "current"
    seed_snapshot(current_dir)

    provider = SnapshotDataProvider(settings)
    first_bundle = provider.load_bundle()
    current_dir.joinpath("daily_recommendations.json").write_text("{broken", encoding="utf-8-sig")

    stale_bundle = provider.load_bundle()
    status = provider.get_status()

    assert first_bundle.stale is False
    assert stale_bundle.stale is True
    assert status.state == "stale"
    assert status.errors
