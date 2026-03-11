import importlib
import json
from pathlib import Path

from service_platform.shared.config import Settings
from service_platform.web.app import create_app

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "service_platform" / "schemas" / "examples"
EXAMPLE_FILES = {
    "model_catalog": EXAMPLE_DIR / "model_catalog.example.json",
    "daily_recommendations": EXAMPLE_DIR / "daily_recommendations.example.json",
    "recent_changes": EXAMPLE_DIR / "recent_changes.example.json",
    "performance_summary": EXAMPLE_DIR / "performance_summary.example.json",
}


def build_settings(tmp_path: Path) -> Settings:
    public_data_dir = tmp_path / "public_data"
    return Settings(
        app_env="test",
        web_host="127.0.0.1",
        web_port=8000,
        public_data_dir=public_data_dir,
        publish_root_dir=public_data_dir,
        feedback_db_path=tmp_path / "feedback.db",
        backup_dir=tmp_path / "backups",
        alert_log_path=tmp_path / "alerts.log",
        alert_webhook_url="",
        alert_throttle_seconds=0,
        log_level="INFO",
        publish_keep_days=14,
        snapshot_source="local",
        snapshot_cache_ttl_seconds=60,
        snapshot_stale_after_hours=24,
        snapshot_gcs_bucket="",
        snapshot_gcs_base_url="",
        feedback_rate_limit_seconds=60,
        feedback_duplicate_window_seconds=3600,
        feedback_message_min_length=10,
        feedback_admin_key="secret-key",
        analytics_window_hours=24,
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
    )


def seed_snapshot(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, source in EXAMPLE_FILES.items():
        output_name = f"{filename}.json"
        target_dir.joinpath(output_name).write_text(
            source.read_text(encoding="utf-8-sig"),
            encoding="utf-8-sig",
        )

    daily = json.loads(EXAMPLE_FILES["daily_recommendations"].read_text(encoding="utf-8-sig"))
    daily["generated_at"] = "2026-03-11T12:00:00Z"
    target_dir.joinpath("daily_recommendations.json").write_text(
        json.dumps(daily, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )

    manifest = {
        "run_id": "test-run",
        "as_of_date": "2026-03-10",
        "generated_at": "2026-03-11T12:00:00Z",
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


def test_home_and_today_pages_render_snapshot_content(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_snapshot(settings.public_data_dir / "current")
    app = create_app(settings)
    client = app.test_client()

    home_response = client.get("/")
    today_response = client.get("/today")

    assert home_response.status_code == 200
    assert "Quality Momentum KR" in home_response.get_data(as_text=True)
    assert today_response.status_code == 200
    assert "Samsung Electronics" in today_response.get_data(as_text=True)


def test_error_page_is_rendered_when_snapshots_are_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/today")
    body = response.get_data(as_text=True)

    assert response.status_code == 503
    assert "현재 데이터 업데이트 중입니다." in body
    assert "상태 페이지 보기" in body


def test_healthz_and_status_display_snapshot_metadata(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_snapshot(settings.public_data_dir / "current")
    app = create_app(settings)
    client = app.test_client()

    health_response = client.get("/healthz")
    status_response = client.get("/status")

    assert health_response.status_code == 200
    assert health_response.get_json()["snapshot_state"] == "healthy"
    assert health_response.get_json()["snapshot_accessible"] is True
    assert health_response.get_json()["last_run_id"] == "test-run"
    assert status_response.status_code == 200
    body = status_response.get_data(as_text=True)
    assert "2026-03-10" in body
    assert "Page Views" in body
    assert "Published Latest" in body


def test_feedback_submission_click_tracking_and_admin_page(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_snapshot(settings.public_data_dir / "current")
    app = create_app(settings)
    client = app.test_client()

    feedback_response = client.post(
        "/feedback",
        data={
            "email": "reader@example.com",
            "message": "Please add more rationale and explain the exits in plain language.",
            "consent": "on",
            "page": "/feedback",
        },
        follow_redirects=True,
    )
    click_response = client.get(
        "/e/click?ticker=005930&model_id=quality_momentum_kr&page=%2Ftoday",
        follow_redirects=False,
    )
    admin_response = client.get("/admin/feedback?access_key=secret-key")

    assert feedback_response.status_code == 200
    assert "정상 접수되었습니다" in feedback_response.get_data(as_text=True)
    assert click_response.status_code == 302
    assert "finance.naver.com" in click_response.headers["Location"]
    assert admin_response.status_code == 200
    assert "reader@example.com" in admin_response.get_data(as_text=True)
    assert "005930" in admin_response.get_data(as_text=True)


def test_admin_page_is_hidden_without_access_key(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/admin/feedback")

    assert response.status_code == 404


def test_status_writes_alert_log_when_snapshot_is_unavailable(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/status")

    assert response.status_code == 200
    assert settings.alert_log_path.exists()
    assert "Snapshot Status Warning" in settings.alert_log_path.read_text(encoding="utf-8")


def test_port_env_overrides_web_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("WEB_PORT", "8000")

    config_module = importlib.import_module("service_platform.shared.config")
    config_module = importlib.reload(config_module)

    assert config_module.get_settings().web_port == 9090
