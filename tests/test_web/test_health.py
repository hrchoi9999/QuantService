import importlib
import json
from pathlib import Path

from service_platform.billing.lightpay import BILLING_PLAN_PRICES
from service_platform.shared.config import Settings
from service_platform.web.app import create_app

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "service_platform" / "schemas" / "examples"
EXAMPLE_FILES = {
    "model_catalog": EXAMPLE_DIR / "model_catalog.example.json",
    "daily_recommendations": EXAMPLE_DIR / "daily_recommendations.example.json",
    "recent_changes": EXAMPLE_DIR / "recent_changes.example.json",
    "performance_summary": EXAMPLE_DIR / "performance_summary.example.json",
}


def build_settings(
    tmp_path: Path,
    *,
    trial_mode: bool = True,
    trial_end_date: str = "2026-06-11",
    allow_higher: bool = True,
    billing_enabled: bool = False,
    notify_allowed_ips: tuple[str, ...] = (),
) -> Settings:
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
        trial_mode=trial_mode,
        trial_default_plan="starter",
        trial_end_date=trial_end_date,
        trial_applies_to="authenticated_only",
        allow_higher_plan_during_trial=allow_higher,
        billing_enabled=billing_enabled,
        billing_mode="test",
        billing_cycle_days=30,
        billing_currency="KRW",
        lightpay_mid="test-mid",
        lightpay_merchant_key="test-merchant-key",
        lightpay_return_url="http://127.0.0.1:8000/billing/return",
        lightpay_notify_url="http://127.0.0.1:8000/billing/notify",
        lightpay_notify_allowed_ips=notify_allowed_ips,
        phone_verification_mode="mock",
        phone_verification_code_ttl_seconds=300,
        phone_verification_preview_enabled=True,
        s2_holdings_csv=tmp_path / "holdings.csv",
        s2_snapshot_csv=tmp_path / "snapshot.csv",
        s2_summary_csv=tmp_path / "summary.csv",
        user_snapshot_dir=tmp_path / "user_current",
    )


def seed_internal_snapshot(
    target_dir: Path,
    *,
    generated_at: str = "2026-03-11T12:00:00Z",
    daily_models: list[dict] | None = None,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, source in EXAMPLE_FILES.items():
        output_name = f"{filename}.json"
        target_dir.joinpath(output_name).write_text(
            source.read_text(encoding="utf-8-sig"),
            encoding="utf-8-sig",
        )

    daily = json.loads(EXAMPLE_FILES["daily_recommendations"].read_text(encoding="utf-8-sig"))
    daily["generated_at"] = generated_at
    if daily_models is not None:
        daily["models"] = daily_models
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


def seed_user_snapshot(
    target_dir: Path,
    *,
    generated_at: str = "2026-03-18T21:42:03",
    include_reports: bool = True,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    models = [
        {
            "user_model_id": "user_1",
            "user_model_name": "Redbot Stable",
            "service_profile": "stable",
            "summary": "Defensive allocation for preserving capital.",
            "risk_label": "low",
            "target_user_type": "Investors who value stability first.",
            "primary_asset_mix": ["bond", "gold", "cash_like"],
            "is_active": True,
        },
        {
            "user_model_id": "user_2",
            "user_model_name": "Redbot Balanced",
            "service_profile": "balanced",
            "summary": "Balanced allocation between growth and defense.",
            "risk_label": "medium",
            "target_user_type": "Investors who want balance.",
            "primary_asset_mix": ["stock", "equity_etf", "bond_short"],
            "is_active": True,
        },
        {
            "user_model_id": "user_3",
            "user_model_name": "Redbot Growth",
            "service_profile": "growth",
            "summary": "Growth-oriented allocation in favorable trends.",
            "risk_label": "high",
            "target_user_type": "Investors who accept volatility.",
            "primary_asset_mix": ["momentum_stock", "growth_etf"],
            "is_active": True,
        },
        {
            "user_model_id": "user_4",
            "user_model_name": "Redbot Auto",
            "service_profile": "auto",
            "summary": "Adaptive strategy that adjusts by regime.",
            "risk_label": "adaptive",
            "target_user_type": "Investors who prefer automatic shifts.",
            "primary_asset_mix": ["multi_asset", "dynamic_allocation"],
            "is_active": True,
        },
    ]
    reports = (
        [
            {
                "user_model_name": "Redbot Stable",
                "service_profile": "stable",
                "summary_text": "Stable strategy summary.",
                "market_view": "Neutral market with defensive positioning.",
                "allocation_items": [
                    {
                        "asset_group": "etf",
                        "display_name": "KODEX Cash ETF",
                        "target_weight": 0.32,
                        "role_summary": "Liquidity buffer",
                        "source_type": "ETF",
                    },
                    {
                        "asset_group": "etf",
                        "display_name": "ACE Gold ETF",
                        "target_weight": 0.18,
                        "role_summary": "Defensive hedge",
                        "source_type": "ETF",
                    },
                ],
                "rationale_items": [
                    "Keep risk limited while the market is neutral.",
                    "Preserve optionality with liquid hedges.",
                ],
                "risk_level": "low",
                "performance_summary": {
                    "headline_metrics": {
                        "full_cagr": 0.0443,
                        "full_mdd": -0.0559,
                        "full_sharpe": 0.6850,
                    },
                    "period_metrics": [
                        {"period": "1Y", "cagr": 0.0958, "mdd": -0.0541, "sharpe": 0.7946},
                        {"period": "FULL", "cagr": 0.0443, "mdd": -0.0559, "sharpe": 0.6850},
                    ],
                },
                "change_log": {
                    "increased_assets": ["KODEX Cash ETF (+5.0%)"],
                    "decreased_assets": ["ACE Gold ETF (-5.0%)"],
                    "change_reason": "Risk control tightened after market momentum cooled.",
                },
                "disclaimer_text": "This material is for informational purposes only.",
            },
            {
                "user_model_name": "Redbot Balanced",
                "service_profile": "balanced",
                "summary_text": "Balanced strategy summary.",
                "market_view": "Neutral regime with selective risk-taking.",
                "allocation_items": [
                    {
                        "asset_group": "stock",
                        "display_name": "Samsung Electronics",
                        "target_weight": 0.12,
                        "role_summary": "Core quality holding",
                        "source_type": "stock",
                    }
                ],
                "rationale_items": ["Blend defense and upside participation."],
                "risk_level": "medium",
                "performance_summary": {
                    "headline_metrics": {
                        "full_cagr": 0.3318,
                        "full_mdd": -0.1332,
                        "full_sharpe": 1.8446,
                    },
                    "period_metrics": [
                        {"period": "1Y", "cagr": 0.8207, "mdd": -0.1332, "sharpe": 2.3773},
                        {"period": "FULL", "cagr": 0.3318, "mdd": -0.1332, "sharpe": 1.8446},
                    ],
                },
                "change_log": {
                    "increased_assets": ["Samsung Electronics (+1.3%)"],
                    "decreased_assets": ["Cash (-1.5%)"],
                    "change_reason": "Risk appetite improved modestly.",
                },
                "disclaimer_text": "This material is for informational purposes only.",
            },
        ]
        if include_reports
        else []
    )
    performance_models = [
        {
            "user_model_name": model["user_model_name"],
            "service_profile": model["service_profile"],
            "risk_label": model["risk_label"],
            "performance_cards": {
                "cagr": 0.10 + index * 0.05,
                "mdd": -0.05 - index * 0.02,
                "sharpe": 0.7 + index * 0.4,
            },
            "period_table": [
                {
                    "period": "1Y",
                    "cagr": 0.1 + index * 0.05,
                    "mdd": -0.05,
                    "sharpe": 0.8 + index * 0.2,
                },
                {
                    "period": "FULL",
                    "cagr": 0.11 + index * 0.05,
                    "mdd": -0.06,
                    "sharpe": 0.7 + index * 0.2,
                },
            ],
            "note": f"Note for {model['user_model_name']}",
        }
        for index, model in enumerate(models)
    ]
    changes = (
        [
            {
                "user_model_name": "Redbot Stable",
                "change_type": "rebalanced",
                "summary": "Defensive exposure was increased.",
                "increase_items": ["KODEX Cash ETF (+5.0%)"],
                "decrease_items": ["ACE Gold ETF (-5.0%)"],
                "reason_text": "The portfolio leaned more defensive after weaker momentum.",
            },
            {
                "user_model_name": "Redbot Growth",
                "change_type": "increase",
                "summary": "Growth exposure was added selectively.",
                "increase_items": ["Samsung Electronics (+1.3%)"],
                "decrease_items": ["Cash (-1.3%)"],
                "reason_text": "Trend strength improved in selected equities.",
            },
        ]
        if include_reports
        else []
    )

    payloads = {
        "user_model_catalog.json": {"as_of_date": "2026-03-18", "models": models},
        "user_recommendation_report.json": {
            "as_of_date": "2026-03-18",
            "generated_at": generated_at,
            "current_market_regime": "neutral",
            "reports": reports,
        },
        "user_performance_summary.json": {
            "as_of_date": "2026-03-18",
            "models": performance_models,
        },
        "user_recent_changes.json": {
            "as_of_date": "2026-03-18",
            "changes": changes,
        },
        "publish_manifest.json": {
            "as_of_date": "2026-03-18",
            "generated_at": generated_at,
            "files": [
                "user_model_catalog.json",
                "user_recommendation_report.json",
                "user_performance_summary.json",
                "user_recent_changes.json",
            ],
            "channel": "user-facing",
            "version": "v1",
        },
    }
    for filename, payload in payloads.items():
        target_dir.joinpath(filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8-sig",
        )


def get_csrf_token(client) -> str:
    with client.session_transaction() as session_data:
        return session_data["csrf_token"]


def get_phone_verification_code(client) -> str:
    with client.session_transaction() as session_data:
        return session_data["phone_verification"]["code"]


def test_user_pages_render_user_snapshot_content(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    home_response = client.get("/")
    today_response = client.get("/today")
    performance_response = client.get("/performance")
    changes_response = client.get("/changes")

    assert home_response.status_code == 200
    assert "Redbot Stable" in home_response.get_data(as_text=True)
    assert today_response.status_code == 200
    assert "Samsung Electronics" in today_response.get_data(as_text=True)
    assert performance_response.status_code == 200
    assert "전략별 성과 비교" in performance_response.get_data(as_text=True)
    assert changes_response.status_code == 200
    assert "최근 변경 내역" in changes_response.get_data(as_text=True)


def test_mock_api_routes_return_snapshot_payloads(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    models_response = client.get("/api/v1/user-models")
    today_response = client.get("/api/v1/recommendation/today")
    profile_response = client.get("/api/v1/recommendation/stable")
    performance_response = client.get("/api/v1/performance/summary")
    changes_response = client.get("/api/v1/changes/recent")
    manifest_response = client.get("/api/v1/publish-status")

    assert models_response.status_code == 200
    assert models_response.get_json()["models"][0]["user_model_name"] == "Redbot Stable"
    assert today_response.status_code == 200
    assert today_response.get_json()["reports"][0]["service_profile"] == "stable"
    assert profile_response.status_code == 200
    assert profile_response.get_json()["report"]["user_model_name"] == "Redbot Stable"
    assert performance_response.status_code == 200
    assert len(performance_response.get_json()["models"]) == 4
    assert changes_response.status_code == 200
    assert changes_response.get_json()["changes"][0]["change_type"] == "rebalanced"
    assert manifest_response.status_code == 200
    assert manifest_response.get_json()["channel"] == "user-facing"


def test_error_page_is_rendered_when_user_snapshots_are_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/today")
    body = response.get_data(as_text=True)

    assert response.status_code == 503
    assert "Temporary Issue" in body
    assert "현재 데이터 업데이트 중입니다." in body


def test_empty_state_is_rendered_when_reports_are_empty(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir, include_reports=False)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/today")

    assert response.status_code == 200
    assert "오늘의 추천 데이터가 아직 없습니다." in response.get_data(as_text=True)


def test_healthz_and_status_display_snapshot_metadata(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    health_response = client.get("/healthz")
    status_response = client.get("/status")

    assert health_response.status_code == 200
    assert health_response.get_json()["snapshot_state"] == "healthy"
    assert health_response.get_json()["snapshot_accessible"] is True
    assert health_response.get_json()["as_of_date"] == "2026-03-18"
    assert status_response.status_code == 200
    body = status_response.get_data(as_text=True)
    assert "user_model_catalog.json" in body
    assert "Page Views" in body


def test_theme_preview_page_renders_selected_theme(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/theme-preview")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Light Red Research" in body
    assert "Primary red #e62c28" in body
    assert "Dark Wine Premium" not in body


def test_pricing_page_shows_billing_disabled_by_default(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, billing_enabled=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/pricing")
    checkout_response = client.post(
        "/billing/checkout", data={"plan_id": "starter", "pay_method": "CARD"}
    )

    assert response.status_code == 200
    assert "Pricing" in response.get_data(as_text=True)
    assert checkout_response.status_code == 404


def test_enabled_billing_checkout_renders_lightpay_form(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, billing_enabled=True, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    app.config["ACCESS_STORE"].register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01012345678",
    )
    client = app.test_client()

    client.post(
        "/login",
        data={"email": "member@example.com", "password": "pass1234", "next": "/pricing"},
        follow_redirects=True,
    )
    response = client.post("/billing/checkout", data={"plan_id": "starter", "pay_method": "CARD"})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "lightpay-checkout-form" in body
    assert "lightpay-checkout-form" in body
    assert str(BILLING_PLAN_PRICES["starter"]) in body


def test_billing_notify_blocks_unlisted_ip(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path, billing_enabled=True, trial_mode=False, notify_allowed_ips=("203.0.113.10",)
    )
    app = create_app(settings)
    client = app.test_client()

    response = client.post(
        "/billing/notify",
        data={"ordNo": "RB-1"},
        headers={"X-Forwarded-For": "198.51.100.22"},
    )

    assert response.status_code == 403
    assert response.get_json()["status"] == "forbidden"


def test_signup_flow_supports_email_accounts_with_phone_verification(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=True)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    request_code_response = client.post(
        "/signup",
        data={"action": "request_code", "phone_number": "010-2222-3333", "next": "/today"},
        follow_redirects=True,
    )
    verification_code = get_phone_verification_code(client)
    signup_response = client.post(
        "/signup",
        data={
            "action": "register",
            "email": "member@gmail.com",
            "password": "pass1234",
            "password_confirm": "pass1234",
            "phone_number": "01022223333",
            "verification_code": verification_code,
            "next": "/today",
        },
        follow_redirects=True,
    )
    login_response = client.post(
        "/login",
        data={"email": "member@gmail.com", "password": "pass1234", "next": "/today"},
        follow_redirects=True,
    )
    me_response = client.get("/me")

    assert request_code_response.status_code == 200
    assert "개발용 인증번호" in request_code_response.get_data(as_text=True)
    assert signup_response.status_code == 200
    assert "Gmail" in signup_response.get_data(as_text=True)
    assert login_response.status_code == 200
    assert "Redbot Stable" in login_response.get_data(as_text=True)
    assert me_response.get_json()["phone_verification_status"] == "verified"
    assert me_response.get_json()["auth_provider"] == "local"


def test_admin_dashboard_and_grant_write_audit_log(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    dashboard_response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "pass1234", "next": "/admin"},
        follow_redirects=True,
    )
    csrf_token = get_csrf_token(client)
    grant_response = client.post(
        "/admin/grant",
        data={
            "email": "member@example.com",
            "plan_id": "pro",
            "expires_at": "2026-12-31",
            "action": "grant",
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    audit_response = client.get("/admin/audit")

    assert dashboard_response.status_code == 200
    assert "Admin Dashboard" in dashboard_response.get_data(as_text=True)
    assert grant_response.status_code == 200
    assert "member@example.com" in grant_response.get_data(as_text=True)
    assert "admin.grant.grant" in audit_response.get_data(as_text=True)
    assert client.get("/admin/billing").status_code == 404


def test_admin_pages_show_phase_policy_and_billing_visibility(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, billing_enabled=True, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    client.post(
        "/login",
        data={"email": "admin@example.com", "password": "pass1234", "next": "/admin"},
        follow_redirects=True,
    )

    dashboard = client.get("/admin")
    billing = client.get("/admin/billing")

    assert dashboard.status_code == 200
    assert "Billing enabled" in dashboard.get_data(as_text=True)
    assert billing.status_code == 200
    assert "Billing Console" in billing.get_data(as_text=True)


def test_admin_publish_snapshot_promotes_selected_internal_snapshot(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_internal_snapshot(
        settings.public_data_dir / "current",
        generated_at="2026-03-11T12:00:00Z",
    )
    seed_internal_snapshot(
        settings.public_data_dir / "published" / "2026-03-12" / "run-2",
        generated_at="2026-03-12T15:00:00Z",
    )
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    client.post(
        "/login",
        data={
            "email": "admin@example.com",
            "password": "pass1234",
            "next": "/admin/publish-snapshots",
        },
        follow_redirects=True,
    )
    csrf_token = get_csrf_token(client)
    response = client.post(
        "/admin/publish-snapshots",
        data={
            "action": "activate",
            "snapshot_label": "2026-03-12/run-2",
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    internal_status = app.config["SNAPSHOT_PROVIDER"].get_status(force_refresh=True)

    assert response.status_code == 200
    assert internal_status.generated_at == "2026-03-12T15:00:00Z"


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
