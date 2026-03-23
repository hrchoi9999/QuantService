import importlib
import json
from datetime import datetime, timezone
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
    generated_at: str | None = None,
    include_reports: bool = True,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if generated_at is None:
        generated_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
    models = [
        {
            "user_model_id": "user_1",
            "user_model_name": "안정형",
            "service_profile": "stable",
            "summary": "채권과 금을 중심으로 방어적인 흐름을 추구하는 전략입니다.",
            "risk_label": "low",
            "target_user_type": "안정성을 우선하는 투자자",
            "primary_asset_mix": ["bond", "gold", "cash_like"],
            "is_active": True,
        },
        {
            "user_model_id": "user_2",
            "user_model_name": "균형형",
            "service_profile": "balanced",
            "summary": "주식과 ETF를 함께 활용해 균형 잡힌 성과를 추구합니다.",
            "risk_label": "medium",
            "target_user_type": "성장과 방어를 함께 보고 싶은 투자자",
            "primary_asset_mix": ["stock", "equity_etf", "cash_like"],
            "is_active": True,
        },
        {
            "user_model_id": "user_3",
            "user_model_name": "성장형",
            "service_profile": "growth",
            "summary": "최근 강한 성장 주식 sleeve를 적극적으로 반영하는 전략입니다.",
            "risk_label": "high",
            "target_user_type": "수익 기회를 적극적으로 추구하는 투자자",
            "primary_asset_mix": ["growth_stock", "growth_etf"],
            "is_active": True,
        },
        {
            "user_model_id": "user_4",
            "user_model_name": "자동전환형",
            "service_profile": "auto",
            "summary": "시장 환경에 따라 비중과 자산 구성을 자동으로 조정합니다.",
            "risk_label": "adaptive",
            "target_user_type": "국면 변화에 자동 대응하고 싶은 투자자",
            "primary_asset_mix": ["multi_asset", "dynamic_allocation"],
            "is_active": True,
        },
    ]
    shared_periods = [
        {"period": "3M", "cagr": 0.19, "mdd": -0.08, "sharpe": 1.42},
        {"period": "6M", "cagr": 0.24, "mdd": -0.09, "sharpe": 1.51},
        {"period": "1Y", "cagr": 0.32, "mdd": -0.11, "sharpe": 1.73},
        {"period": "2Y", "cagr": 0.18, "mdd": -0.12, "sharpe": 1.21},
        {"period": "3Y", "cagr": 0.16, "mdd": -0.12, "sharpe": 1.14},
        {"period": "5Y", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
        {"period": "FULL", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
    ]
    reports = (
        [
            {
                "user_model_name": "안정형",
                "service_profile": "stable",
                "summary_text": "채권과 금 중심의 방어형 포트폴리오입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "target_weight": 0.12,
                        "role_summary": "방어 보완 자산",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "069500",
                        "asset_group": "etf",
                        "display_name": "KODEX 200",
                        "target_weight": 0.28,
                        "role_summary": "ETF 코어 노출",
                        "source_type": "etf",
                    },
                    {
                        "security_code": None,
                        "asset_group": "cash",
                        "display_name": "현금/대기자금",
                        "target_weight": 0.18,
                        "role_summary": "유동성 및 완충 역할",
                        "source_type": "cash",
                    },
                ],
                "rationale_items": [
                    "주식 비중 확대보다 안정 자산 유지가 유리합니다.",
                    "시장 변동성 구간에서 방어 역할이 중요합니다.",
                ],
                "risk_level": "low",
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "cagr": 0.12,
                        "mdd": -0.07,
                        "sharpe": 1.18,
                        "trailing_3m": {"period": "3M", "cagr": 0.08, "mdd": -0.05, "sharpe": 1.01},
                        "trailing_6m": {"period": "6M", "cagr": 0.10, "mdd": -0.06, "sharpe": 1.11},
                        "trailing_1y": {"period": "1Y", "cagr": 0.12, "mdd": -0.07, "sharpe": 1.18},
                        "reference_5y": {
                            "period": "5Y",
                            "cagr": 0.09,
                            "mdd": -0.08,
                            "sharpe": 0.94,
                        },
                        "reference_full": {
                            "period": "FULL",
                            "cagr": 0.09,
                            "mdd": -0.08,
                            "sharpe": 0.94,
                        },
                    },
                    "period_metrics": [
                        {"period": "3M", "cagr": 0.08, "mdd": -0.05, "sharpe": 1.01},
                        {"period": "6M", "cagr": 0.10, "mdd": -0.06, "sharpe": 1.11},
                        {"period": "1Y", "cagr": 0.12, "mdd": -0.07, "sharpe": 1.18},
                        {"period": "2Y", "cagr": 0.10, "mdd": -0.08, "sharpe": 1.02},
                        {"period": "3Y", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.97},
                        {"period": "5Y", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
                        {"period": "FULL", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
                    ],
                },
                "change_log": {
                    "increase_items": [
                        {
                            "display_name": "삼성전자",
                            "security_code": "005930",
                            "delta_weight": 0.013,
                            "direction": "increase",
                        }
                    ],
                    "decrease_items": [
                        {
                            "display_name": "현금/대기자금",
                            "security_code": None,
                            "delta_weight": -0.010,
                            "direction": "decrease",
                        }
                    ],
                    "change_reason": "방어 자산을 유지하되 일부 주식 비중을 보강했습니다.",
                },
                "disclaimer_text": "이 자료는 정보 제공 목적이며 투자 자문이 아닙니다.",
            },
            {
                "user_model_name": "균형형",
                "service_profile": "balanced",
                "summary_text": "국내 주식과 ETF를 함께 담는 균형형 포트폴리오입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "target_weight": 0.16,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "000270",
                        "asset_group": "stock",
                        "display_name": "기아",
                        "target_weight": 0.14,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "069500",
                        "asset_group": "etf",
                        "display_name": "KODEX 200",
                        "target_weight": 0.20,
                        "role_summary": "ETF 코어 노출",
                        "source_type": "etf",
                    },
                    {
                        "security_code": "192720",
                        "asset_group": "etf",
                        "display_name": "파워 고배당저변동성",
                        "target_weight": 0.18,
                        "role_summary": "ETF 분산 노출",
                        "source_type": "etf",
                    },
                    {
                        "security_code": None,
                        "asset_group": "cash",
                        "display_name": "현금/대기자금",
                        "target_weight": 0.08,
                        "role_summary": "유동성 및 완충 역할",
                        "source_type": "cash",
                    },
                ],
                "rationale_items": [
                    "국내 ETF와 주식을 함께 담아 분산합니다.",
                    "중립 구간에서 균형 있는 비중 유지가 적절합니다.",
                ],
                "risk_level": "medium",
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "cagr": 0.32,
                        "mdd": -0.11,
                        "sharpe": 1.73,
                        "trailing_3m": {"period": "3M", "cagr": 0.19, "mdd": -0.08, "sharpe": 1.42},
                        "trailing_6m": {"period": "6M", "cagr": 0.24, "mdd": -0.09, "sharpe": 1.51},
                        "trailing_1y": {"period": "1Y", "cagr": 0.32, "mdd": -0.11, "sharpe": 1.73},
                        "reference_5y": {
                            "period": "5Y",
                            "cagr": 0.15,
                            "mdd": -0.12,
                            "sharpe": 1.08,
                        },
                        "reference_full": {
                            "period": "FULL",
                            "cagr": 0.15,
                            "mdd": -0.12,
                            "sharpe": 1.08,
                        },
                    },
                    "period_metrics": [dict(item) for item in shared_periods],
                },
                "change_log": {
                    "increase_items": [
                        {
                            "display_name": "삼성전자",
                            "security_code": "005930",
                            "delta_weight": 0.013,
                            "direction": "increase",
                        }
                    ],
                    "decrease_items": [
                        {
                            "display_name": "현금/대기자금",
                            "security_code": None,
                            "delta_weight": -0.015,
                            "direction": "decrease",
                        }
                    ],
                    "change_reason": "주식과 ETF의 균형 비중을 유지하도록 조정했습니다.",
                },
                "disclaimer_text": "이 자료는 정보 제공 목적이며 투자 자문이 아닙니다.",
            },
            {
                "user_model_name": "성장형",
                "service_profile": "growth",
                "summary_text": "최근 강한 성장 주식 sleeve를 적극적으로 반영하는 전략입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "target_weight": 0.22,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "000660",
                        "asset_group": "stock",
                        "display_name": "SK하이닉스",
                        "target_weight": 0.18,
                        "role_summary": "성장 주식 sleeve",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "069500",
                        "asset_group": "etf",
                        "display_name": "KODEX 200",
                        "target_weight": 0.10,
                        "role_summary": "ETF 보완 노출",
                        "source_type": "etf",
                    },
                    {
                        "security_code": None,
                        "asset_group": "cash",
                        "display_name": "현금/대기자금",
                        "target_weight": 0.04,
                        "role_summary": "유동성 및 완충 역할",
                        "source_type": "cash",
                    },
                ],
                "rationale_items": [
                    "최근 1년 성과가 강한 성장 주식 sleeve를 반영합니다.",
                    "중립 구간에서도 성장 전략의 우위를 유지합니다.",
                ],
                "risk_level": "high",
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "cagr": 0.51,
                        "mdd": -0.16,
                        "sharpe": 2.14,
                        "trailing_3m": {"period": "3M", "cagr": 0.28, "mdd": -0.10, "sharpe": 1.64},
                        "trailing_6m": {"period": "6M", "cagr": 0.35, "mdd": -0.13, "sharpe": 1.89},
                        "trailing_1y": {"period": "1Y", "cagr": 0.51, "mdd": -0.16, "sharpe": 2.14},
                        "reference_5y": {
                            "period": "5Y",
                            "cagr": 0.24,
                            "mdd": -0.18,
                            "sharpe": 1.31,
                        },
                        "reference_full": {
                            "period": "FULL",
                            "cagr": 0.24,
                            "mdd": -0.18,
                            "sharpe": 1.31,
                        },
                    },
                    "period_metrics": [
                        {"period": "3M", "cagr": 0.28, "mdd": -0.10, "sharpe": 1.64},
                        {"period": "6M", "cagr": 0.35, "mdd": -0.13, "sharpe": 1.89},
                        {"period": "1Y", "cagr": 0.51, "mdd": -0.16, "sharpe": 2.14},
                        {"period": "2Y", "cagr": 0.30, "mdd": -0.18, "sharpe": 1.42},
                        {"period": "3Y", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                        {"period": "5Y", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                        {"period": "FULL", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                    ],
                },
                "change_log": {
                    "increase_items": [
                        {
                            "display_name": "SK하이닉스",
                            "security_code": "000660",
                            "delta_weight": 0.021,
                            "direction": "increase",
                        }
                    ],
                    "decrease_items": [
                        {
                            "display_name": "현금/대기자금",
                            "security_code": None,
                            "delta_weight": -0.012,
                            "direction": "decrease",
                        }
                    ],
                    "change_reason": "최근 1년 성과 우위가 있는 성장 주식 비중을 확대했습니다.",
                },
                "disclaimer_text": "이 자료는 정보 제공 목적이며 투자 자문이 아닙니다.",
            },
            {
                "user_model_name": "자동전환형",
                "service_profile": "auto",
                "summary_text": "시장 국면에 따라 비중과 자산 구성을 자동으로 조정합니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "target_weight": 0.16,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "069500",
                        "asset_group": "etf",
                        "display_name": "KODEX 200",
                        "target_weight": 0.20,
                        "role_summary": "ETF 코어 노출",
                        "source_type": "etf",
                    },
                    {
                        "security_code": None,
                        "asset_group": "cash",
                        "display_name": "현금/대기자금",
                        "target_weight": 0.08,
                        "role_summary": "유동성 및 완충 역할",
                        "source_type": "cash",
                    },
                ],
                "rationale_items": [
                    "시장 변화에 따라 비중을 유연하게 조정합니다.",
                    "중립 구간에서는 균형형과 유사해질 수 있습니다.",
                ],
                "risk_level": "adaptive",
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "cagr": 0.32,
                        "mdd": -0.11,
                        "sharpe": 1.73,
                        "trailing_3m": {"period": "3M", "cagr": 0.19, "mdd": -0.08, "sharpe": 1.42},
                        "trailing_6m": {"period": "6M", "cagr": 0.24, "mdd": -0.09, "sharpe": 1.51},
                        "trailing_1y": {"period": "1Y", "cagr": 0.32, "mdd": -0.11, "sharpe": 1.73},
                        "reference_5y": {
                            "period": "5Y",
                            "cagr": 0.15,
                            "mdd": -0.12,
                            "sharpe": 1.08,
                        },
                        "reference_full": {
                            "period": "FULL",
                            "cagr": 0.15,
                            "mdd": -0.12,
                            "sharpe": 1.08,
                        },
                    },
                    "period_metrics": [dict(item) for item in shared_periods],
                },
                "change_log": {
                    "increase_items": [
                        {
                            "display_name": "삼성전자",
                            "security_code": "005930",
                            "delta_weight": 0.013,
                            "direction": "increase",
                        }
                    ],
                    "decrease_items": [
                        {
                            "display_name": "현금/대기자금",
                            "security_code": None,
                            "delta_weight": -0.015,
                            "direction": "decrease",
                        }
                    ],
                    "change_reason": "시장 국면 변화에 맞춰 주식과 현금 비중을 조정했습니다.",
                },
                "disclaimer_text": "이 자료는 정보 제공 목적이며 투자 자문이 아닙니다.",
            },
        ]
        if include_reports
        else []
    )
    performance_models = [
        {
            "user_model_name": "안정형",
            "service_profile": "stable",
            "risk_label": "low",
            "performance_cards": {
                "primary_period": "1Y",
                "cagr": 0.12,
                "mdd": -0.07,
                "sharpe": 1.18,
            },
            "period_table": [
                {"period": "3M", "cagr": 0.08, "mdd": -0.05, "sharpe": 1.01},
                {"period": "6M", "cagr": 0.10, "mdd": -0.06, "sharpe": 1.11},
                {"period": "1Y", "cagr": 0.12, "mdd": -0.07, "sharpe": 1.18},
                {"period": "2Y", "cagr": 0.10, "mdd": -0.08, "sharpe": 1.02},
                {"period": "3Y", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.97},
                {"period": "5Y", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
                {"period": "FULL", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
            ],
            "reference_metrics": {
                "five_year": {"period": "5Y", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
                "full": {"period": "FULL", "cagr": 0.09, "mdd": -0.08, "sharpe": 0.94},
            },
            "note": "안정 자산 중심으로 변동성을 낮춘 전략입니다.",
        },
        {
            "user_model_name": "균형형",
            "service_profile": "balanced",
            "risk_label": "medium",
            "performance_cards": {
                "primary_period": "1Y",
                "cagr": 0.32,
                "mdd": -0.11,
                "sharpe": 1.73,
            },
            "period_table": [dict(item) for item in shared_periods],
            "reference_metrics": {
                "five_year": {"period": "5Y", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
                "full": {"period": "FULL", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
            },
            "note": "국내 주식과 ETF를 함께 담는 균형형 전략입니다.",
        },
        {
            "user_model_name": "성장형",
            "service_profile": "growth",
            "risk_label": "high",
            "performance_cards": {
                "primary_period": "1Y",
                "cagr": 0.51,
                "mdd": -0.16,
                "sharpe": 2.14,
            },
            "period_table": [
                {"period": "3M", "cagr": 0.28, "mdd": -0.10, "sharpe": 1.64},
                {"period": "6M", "cagr": 0.35, "mdd": -0.13, "sharpe": 1.89},
                {"period": "1Y", "cagr": 0.51, "mdd": -0.16, "sharpe": 2.14},
                {"period": "2Y", "cagr": 0.30, "mdd": -0.18, "sharpe": 1.42},
                {"period": "3Y", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                {"period": "5Y", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                {"period": "FULL", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
            ],
            "reference_metrics": {
                "five_year": {"period": "5Y", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
                "full": {"period": "FULL", "cagr": 0.24, "mdd": -0.18, "sharpe": 1.31},
            },
            "note": "최근 1년 성과가 강한 성장 주식 sleeve를 반영합니다.",
        },
        {
            "user_model_name": "자동전환형",
            "service_profile": "auto",
            "risk_label": "adaptive",
            "performance_cards": {
                "primary_period": "1Y",
                "cagr": 0.32,
                "mdd": -0.11,
                "sharpe": 1.73,
            },
            "period_table": [dict(item) for item in shared_periods],
            "reference_metrics": {
                "five_year": {"period": "5Y", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
                "full": {"period": "FULL", "cagr": 0.15, "mdd": -0.12, "sharpe": 1.08},
            },
            "note": "시장 변화에 맞춰 비중을 자동으로 조정하는 전략입니다.",
        },
    ]
    changes = (
        [
            {
                "user_model_name": "안정형",
                "service_profile": "stable",
                "change_type": "rebalanced",
                "summary": "방어 자산 중심 비중을 조정했습니다.",
                "increase_items": [
                    {
                        "display_name": "삼성전자",
                        "security_code": "005930",
                        "delta_weight": 0.013,
                        "direction": "increase",
                    }
                ],
                "decrease_items": [
                    {
                        "display_name": "현금/대기자금",
                        "security_code": None,
                        "delta_weight": -0.010,
                        "direction": "decrease",
                    }
                ],
                "reason_text": "방어 자산과 주식의 균형을 다시 맞췄습니다.",
            },
            {
                "user_model_name": "성장형",
                "service_profile": "growth",
                "change_type": "increase",
                "summary": "성장 주식 sleeve 비중을 확대했습니다.",
                "increase_items": [
                    {
                        "display_name": "SK하이닉스",
                        "security_code": "000660",
                        "delta_weight": 0.021,
                        "direction": "increase",
                    }
                ],
                "decrease_items": [
                    {
                        "display_name": "현금/대기자금",
                        "security_code": None,
                        "delta_weight": -0.012,
                        "direction": "decrease",
                    }
                ],
                "reason_text": "최근 1년 성과 우위가 있는 성장 주식 비중을 확대했습니다.",
            },
        ]
        if include_reports
        else []
    )

    period_total_returns = {
        "3M": 0.1496,
        "6M": 0.2648,
        "1Y": 0.3212,
        "2Y": 0.3984,
        "3Y": 0.5241,
        "5Y": 0.7820,
        "FULL": 1.0840,
    }

    def apply_total_return(metric: dict) -> None:
        period = metric.get("period")
        if period:
            metric["total_return"] = period_total_returns.get(period, metric.get("cagr"))

    for report in reports:
        headline = report["performance_summary"]["headline_metrics"]
        headline["total_return"] = period_total_returns.get(
            headline.get("primary_period"), headline.get("cagr")
        )
        for key in ("trailing_3m", "trailing_6m", "trailing_1y", "reference_5y", "reference_full"):
            if key in headline:
                apply_total_return(headline[key])
        for row in report["performance_summary"]["period_metrics"]:
            apply_total_return(row)

    for row in performance_models:
        cards = row["performance_cards"]
        cards["display_metric"] = "cagr"
        cards["total_return"] = period_total_returns.get(
            cards.get("primary_period"), cards.get("cagr")
        )
        for period_row in row["period_table"]:
            apply_total_return(period_row)
        for metric in row["reference_metrics"].values():
            apply_total_return(metric)

    payloads = {
        "user_model_catalog.json": {"as_of_date": "2026-03-20", "models": models},
        "user_recommendation_report.json": {
            "as_of_date": "2026-03-20",
            "generated_at": generated_at,
            "current_market_regime": "neutral",
            "reports": reports,
        },
        "user_performance_summary.json": {
            "as_of_date": "2026-03-20",
            "models": performance_models,
        },
        "user_recent_changes.json": {
            "as_of_date": "2026-03-20",
            "changes": changes,
        },
        "publish_manifest.json": {
            "as_of_date": "2026-03-20",
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


def get_phone_verification_code(client) -> str:
    with client.session_transaction() as session_state:
        payload = session_state.get("phone_verification") or {}
        return payload.get("code", "")


def get_csrf_token(client) -> str:
    with client.session_transaction() as session_state:
        token = session_state.get("csrf_token", "")
        return token


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
    assert "안정형" in home_response.get_data(as_text=True)
    assert today_response.status_code == 200
    today_body = today_response.get_data(as_text=True)
    assert "주식 sleeve 비중" in today_body
    assert "ETF sleeve 비중" in today_body
    assert "현금성 비중" in today_body
    assert "주식 상위 종목" in today_body
    assert "ETF 상위 종목" in today_body
    assert "현금성 자산" in today_body
    assert "(005930)" in today_body
    assert "현금/대기자금 (None)" not in today_body
    assert "성장형 해석" in today_body
    assert "S3 성격의 성장 sleeve" in today_body
    assert "5Y" not in today_body
    assert "FULL" not in today_body

    assert performance_response.status_code == 200
    performance_body = performance_response.get_data(as_text=True)
    assert "1Y headline 비교" in performance_body
    assert "참고 지표" not in performance_body
    assert all(period in performance_body for period in ["1Y", "2Y", "3Y", "6M", "3M"])
    assert "5Y" not in performance_body
    assert "FULL" not in performance_body
    assert "Total Return" in performance_body
    assert "자동전환형" in performance_body
    assert "MDD가 같은 값으로 보일 수 있습니다." in performance_body

    assert changes_response.status_code == 200
    changes_body = changes_response.get_data(as_text=True)
    assert "modern-change-card" in changes_body
    assert "(000660)" in changes_body
    assert "현금/대기자금 (None)" not in changes_body


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
    manifest_alias_response = client.get("/api/v1/manifest")

    assert models_response.status_code == 200
    assert models_response.get_json()["models"][0]["user_model_name"] == "안정형"
    assert today_response.status_code == 200
    assert today_response.get_json()["reports"][0]["service_profile"] == "stable"
    assert profile_response.status_code == 200
    assert profile_response.get_json()["report"]["user_model_name"] == "안정형"
    assert performance_response.status_code == 200
    assert len(performance_response.get_json()["models"]) == 4
    assert changes_response.status_code == 200
    assert changes_response.get_json()["changes"][0]["change_type"] == "rebalanced"
    assert (
        changes_response.get_json()["changes"][0]["increase_items"][0]["security_code"] == "005930"
    )
    assert manifest_response.status_code == 200
    assert manifest_alias_response.status_code == 200
    assert manifest_response.get_json()["channel"] == "user-facing"
    assert manifest_alias_response.get_json() == manifest_response.get_json()


def test_error_page_is_rendered_when_user_snapshots_are_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/today")
    body = response.get_data(as_text=True)

    assert response.status_code == 503
    assert "Temporary Issue" in body
    assert "Temporary Issue" in body


def test_empty_state_is_rendered_when_reports_are_empty(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir, include_reports=False)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/today")

    assert response.status_code == 200
    assert "empty-shell" in response.get_data(as_text=True)


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
    assert health_response.get_json()["as_of_date"] == "2026-03-20"
    assert status_response.status_code == 200
    body = status_response.get_data(as_text=True)
    assert "public-status-card" in body
    assert "status-note-box" in body


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
    assert verification_code.isdigit() and len(verification_code) == 6
    assert signup_response.status_code == 200
    assert "Gmail" in signup_response.get_data(as_text=True)
    assert login_response.status_code == 200
    assert "안내" in login_response.get_data(as_text=True)
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
