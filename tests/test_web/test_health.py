import importlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from service_platform.billing.lightpay import BILLING_PLAN_PRICES
from service_platform.shared.config import Settings
from service_platform.web.app import create_app
from service_platform.web.market_analysis_api import MarketAnalysisMockApi

EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "service_platform" / "schemas" / "examples"
EXAMPLE_FILES = {
    "model_catalog": EXAMPLE_DIR / "model_catalog.example.json",
    "daily_recommendations": EXAMPLE_DIR / "daily_recommendations.example.json",
    "recent_changes": EXAMPLE_DIR / "recent_changes.example.json",
    "performance_summary": EXAMPLE_DIR / "performance_summary.example.json",
}


REFERENCE_CONTEXT_STABLE = "변동성보다 안정성과 방어를 우선적으로 참고하려는 이용자"
REFERENCE_CONTEXT_BALANCED = "중장기 성장성과 분산 구성을 함께 참고하려는 이용자"
REFERENCE_CONTEXT_GROWTH = "높은 변동성을 감수하더라도 성장 중심 구성을 참고하려는 이용자"
REFERENCE_CONTEXT_AUTO = "시장 상황에 따라 자동 조정되는 공개 모델 기준안을 참고하려는 이용자"
COMPLIANCE_DISCLAIMER = (
    "이 자료는 공개 규칙 기반 모델 정보와 백테스트 결과를 설명하기 위한 참고자료이며 "
    "특정 개인에 대한 투자자문이나 실제 매매 지시가 아닙니다."
)
MARKET_REFERENCE_NOTE = (
    "지수 흐름은 비교적 우호적이지만 내부 종목 확산과 위험 지표를 함께 " "살펴볼 구간입니다."
)
MARKET_NOTICE_BODY = [
    "본 정보는 공개된 기준에 따라 산출된 시장 브리핑용 참고 정보입니다.",
    ("특정 이용자의 투자목적, 재산상황, 투자경험 또는 위험선호를 반영한 " "개별 자문이 아닙니다."),
    ("투자판단은 이용자 본인의 책임이며, 자산가격 변동에 따라 원금손실이 " "발생할 수 있습니다."),
]
MARKET_NOTICE_PERFORMANCE_NOTE = "시장상태 정보는 모델 해석을 돕기 위한 참고자료입니다."


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
        market_analysis_dir=tmp_path / "market_analysis" / "current",
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
            "reference_usage_context": REFERENCE_CONTEXT_STABLE,
            "target_user_type": REFERENCE_CONTEXT_STABLE,
            "compliance_metadata": {"is_personalized_advice": False},
            "primary_asset_mix": ["bond", "gold", "cash_like"],
            "is_active": True,
        },
        {
            "user_model_id": "user_2",
            "user_model_name": "균형형",
            "service_profile": "balanced",
            "summary": "주식과 ETF를 함께 활용해 균형 잡힌 성과를 추구합니다.",
            "risk_label": "medium",
            "reference_usage_context": REFERENCE_CONTEXT_BALANCED,
            "target_user_type": REFERENCE_CONTEXT_BALANCED,
            "compliance_metadata": {"is_personalized_advice": False},
            "primary_asset_mix": ["stock", "equity_etf", "cash_like"],
            "is_active": True,
        },
        {
            "user_model_id": "user_3",
            "user_model_name": "성장형",
            "service_profile": "growth",
            "summary": "최근 강한 성장 주식 sleeve를 적극적으로 반영하는 전략입니다.",
            "risk_label": "high",
            "reference_usage_context": REFERENCE_CONTEXT_GROWTH,
            "target_user_type": REFERENCE_CONTEXT_GROWTH,
            "compliance_metadata": {"is_personalized_advice": False},
            "primary_asset_mix": ["growth_stock", "growth_etf"],
            "is_active": True,
        },
        {
            "user_model_id": "user_4",
            "user_model_name": "자동전환형",
            "service_profile": "auto",
            "summary": "시장 환경에 따라 비중과 자산 구성을 자동으로 조정합니다.",
            "risk_label": "adaptive",
            "reference_usage_context": REFERENCE_CONTEXT_AUTO,
            "target_user_type": REFERENCE_CONTEXT_AUTO,
            "compliance_metadata": {"is_personalized_advice": False},
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
                "disclaimer_text": COMPLIANCE_DISCLAIMER,
                "compliance_metadata": {
                    "is_personalized_advice": False,
                    "is_one_to_one_advisory": False,
                    "is_actual_trade_instruction": False,
                },
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
                "disclaimer_text": COMPLIANCE_DISCLAIMER,
                "compliance_metadata": {
                    "is_personalized_advice": False,
                    "is_one_to_one_advisory": False,
                    "is_actual_trade_instruction": False,
                },
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
                "disclaimer_text": COMPLIANCE_DISCLAIMER,
                "compliance_metadata": {
                    "is_personalized_advice": False,
                    "is_one_to_one_advisory": False,
                    "is_actual_trade_instruction": False,
                },
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
                "disclaimer_text": COMPLIANCE_DISCLAIMER,
                "compliance_metadata": {
                    "is_personalized_advice": False,
                    "is_one_to_one_advisory": False,
                    "is_actual_trade_instruction": False,
                },
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
        "user_model_snapshot_report.json": {
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
                "user_model_snapshot_report.json",
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


def seed_market_analysis_snapshot(
    target_dir: Path,
    *,
    asof: str = "2026-03-23T19:00:00+09:00",
    state_label: str = "중립",
    ai_briefs_enabled: bool = True,
    ai_providers: list[dict] | None = None,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    compliance_meta = {
        "public_same_for_all_users": True,
        "non_personalized": True,
        "advisory_action_signal": False,
        "intended_use": "market_briefing_reference",
    }
    notice_block = {
        "title": "주의사항",
        "body": MARKET_NOTICE_BODY,
        "performance_link_note": MARKET_NOTICE_PERFORMANCE_NOTE,
    }
    manifest = {
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "consumer": "QuantService",
        "handoff_version": "2026-03-23-p1",
        "freshness": {
            "target_update_interval_minutes": 60,
            "consumer_warning_after_minutes": 90,
            "consumer_stale_after_minutes": 180,
        },
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
    }
    home = {
        "market": "KR",
        "asof": asof,
        "hero": {
            "state_label": state_label,
            "state_score": 0.2907,
            "summary_line": "추세와 방어심리가 엇갈려 뚜렷한 우세 방향은 아직 제한적입니다.",
            "change_vs_prev": "중립 -> 중립",
            "reference_note": MARKET_REFERENCE_NOTE,
        },
        "top_signals": ["20일선 위 종목 비율 낮음", "변동성 확대"],
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
    }
    today = {
        "market": "KR",
        "asof": asof,
        "market_bridge": {
            "market": "KR",
            "asof": asof,
            "state_label": state_label,
            "state_score": 0.2907,
            "market_tone": "중립 해석 환경",
            "reference_text": MARKET_REFERENCE_NOTE,
            "compliance_meta": compliance_meta,
            "notice_block": notice_block,
        },
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
    }
    ai_briefs = {
        "enabled": ai_briefs_enabled,
        "title": "시장 브리핑 참고",
        "layout": "two-column",
        "compliance_meta": compliance_meta,
        "providers": (
            ai_providers
            if ai_providers is not None
            else [
                {
                    "provider": "chatgpt",
                    "label": "ChatGPT",
                    "theme_label": "시장 해석 참고",
                    "enabled": True,
                    "generated_at": asof,
                    "source": "openai:gpt-4.1-mini",
                    "summary_lines": [
                        "추세는 살아 있지만 속도는 과열 구간이 아닙니다.",
                        "대형주 중심 강세가 유지되지만 확산 폭은 점검이 필요합니다.",
                        "방어 자산 선호는 낮아져 주식 비중 유지가 가능합니다.",
                        "신규 추격 매수보다 보유 종목 관리가 유리합니다.",
                    ],
                },
                {
                    "provider": "gemini",
                    "label": "제미나이",
                    "theme_label": "시장 분위기",
                    "enabled": True,
                    "generated_at": asof,
                    "source": "gemini:gemini-2.5-flash",
                    "summary_lines": [
                        "시장 건강도는 양호하지만 단기 변동성은 남아 있습니다.",
                        "중립 이상의 흐름이 유지돼 전략별 선별 대응이 유효합니다.",
                        "지수보다 개별 강한 종목 중심 접근이 적절합니다.",
                        "비중 확대는 단계적으로 접근하는 편이 안전합니다.",
                    ],
                },
            ]
        ),
    }
    page = {
        "market": "KR",
        "asof": asof,
        "ai_briefs": ai_briefs,
        "header_state": {
            "label": state_label,
            "score": 0.2907,
            "prev_label": "중립",
            "change_direction": "unchanged",
        },
        "component_cards": [
            {
                "key": "trend",
                "label": "시장 방향",
                "score": 0.1,
                "summary": "대형주는 버티지만 추세 확산은 아직 뚜렷하지 않습니다.",
            },
            {
                "key": "breadth",
                "label": "시장 건강도",
                "score": 1.9,
                "summary": "상승 흐름이 개별 종목으로 비교적 넓게 확산되고 있습니다.",
            },
            {
                "key": "risk",
                "label": "시장 흔들림",
                "score": -3.0,
                "summary": "최근 변동성과 낙폭이 커져 방어적 해석이 필요합니다.",
            },
            {
                "key": "defensive_flow",
                "label": "방어자산 선호도",
                "score": 1.7,
                "summary": "방어 ETF 상대강도가 높지 않아 주식 선호가 상대적으로 유지됩니다.",
            },
        ],
        "signal_lists": {
            "positive_points": ["60일선 위 종목 비율 양호", "코스피 1개월 상승 흐름"],
            "warning_points": ["20일선 위 종목 비율 낮음", "변동성 확대"],
            "observation_note": MARKET_REFERENCE_NOTE,
        },
        "metrics": {
            "kospi_20d_ret": 0.0388,
            "kospi_60d_ret": 0.1174,
            "kosdaq_20d_ret": 0.0321,
            "above_20dma_ratio": 0.4469,
            "above_60dma_ratio": 0.7045,
            "adv_dec_ratio": 2.52,
            "new_high_count": 31.0,
            "new_low_count": 1.0,
            "realized_vol_20d": 0.2885,
            "drawdown_20d": -0.5376,
            "usdkrw_20d_ret": -0.0134,
            "rate_cd91_20d_chg": -0.4305,
            "rate_ktb3y_20d_chg": -0.3340,
        },
        "summary_line": "추세와 방어심리가 엇갈려 뚜렷한 우세 방향은 아직 제한적입니다.",
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
    }
    api_summary = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/summary?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": {
            "market": "KR",
            "asof": asof,
            "state_label": state_label,
            "state_score": 0.2907,
            "summary_line": home["hero"]["summary_line"],
            "change_vs_prev": "중립 -> 중립",
            "top_signals": home["top_signals"],
            "reference_note": home["hero"]["reference_note"],
            "compliance_meta": compliance_meta,
            "notice_block": notice_block,
        },
    }
    api_detail = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/detail?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": {
            "market": "KR",
            "asof": asof,
            "state": page["header_state"],
            "components": {
                item["key"]: {
                    "score": item["score"],
                    "label": item["label"],
                    "summary": item["summary"],
                }
                for item in page["component_cards"]
            },
            "metrics": page["metrics"],
            "positive_points": page["signal_lists"]["positive_points"],
            "warning_points": page["signal_lists"]["warning_points"],
            "observation_note": page["signal_lists"]["observation_note"],
            "compliance_meta": compliance_meta,
            "notice_block": notice_block,
        },
    }
    api_today = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/today-bridge?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": today["market_bridge"],
    }
    api_home = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/home?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": home,
    }
    api_page = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/page?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": page,
    }

    files = {
        "quantservice_market_manifest.json": manifest,
        "quantservice_market_home.json": home,
        "quantservice_market_today.json": today,
        "quantservice_market_page.json": page,
        "api_v1_market_analysis_home.json": api_home,
        "api_v1_market_analysis_page.json": api_page,
        "api_v1_market_analysis_summary.json": api_summary,
        "api_v1_market_analysis_detail.json": api_detail,
        "api_v1_market_analysis_today_bridge.json": api_today,
    }
    for filename, payload in files.items():
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


def prime_csrf(client, path: str) -> str:
    client.get(path)
    return get_csrf_token(client)


def login_user(
    client, *, email: str, password: str, next_url: str = "/today", follow_redirects: bool = True
):
    csrf_token = prime_csrf(client, f"/login?next={next_url}")
    return client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "next": next_url,
            "csrf_token": csrf_token,
        },
        follow_redirects=follow_redirects,
    )


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
    assert "이번 주 모델 기준안" in today_body
    assert "참고 이용자 유형" in today_body
    assert "공개 규칙 기반 모델 정보" in today_body
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
    assert "1Y 핵심 지표 비교" in performance_body
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
    today_response = client.get("/api/v1/model-snapshots/today")
    weekly_today_response = client.get("/api/v1/model-weekly/today")
    legacy_today_response = client.get("/api/v1/recommendation/today")
    profile_response = client.get("/api/v1/model-snapshots/stable")
    weekly_profile_response = client.get("/api/v1/model-weekly/stable")
    legacy_profile_response = client.get("/api/v1/recommendation/stable")
    performance_response = client.get("/api/v1/performance/summary")
    performance_alias_response = client.get("/api/v1/model-performance/summary")
    changes_response = client.get("/api/v1/changes/recent")
    manifest_response = client.get("/api/v1/publish-status")
    manifest_alias_response = client.get("/api/v1/manifest")

    assert models_response.status_code == 200
    assert models_response.get_json()["models"][0]["user_model_name"] == "안정형"
    assert today_response.status_code == 200
    assert weekly_today_response.status_code == 200
    assert legacy_today_response.status_code == 404
    assert today_response.get_json()["reports"][0]["service_profile"] == "stable"
    assert weekly_today_response.get_json() == today_response.get_json()
    assert "target_user_type" not in today_response.get_json()["reports"][0]
    assert profile_response.status_code == 200
    assert weekly_profile_response.status_code == 200
    assert legacy_profile_response.status_code == 404
    assert profile_response.get_json()["report"]["user_model_name"] == "안정형"
    assert weekly_profile_response.get_json() == profile_response.get_json()
    assert "target_user_type" not in profile_response.get_json()["report"]
    assert performance_response.status_code == 200
    assert performance_alias_response.status_code == 200
    assert performance_alias_response.get_json() == performance_response.get_json()
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

    login_user(
        client,
        email="member@example.com",
        password="pass1234",
        next_url="/pricing",
        follow_redirects=True,
    )
    csrf_token = get_csrf_token(client)
    response = client.post(
        "/billing/checkout",
        data={"plan_id": "starter", "pay_method": "CARD", "csrf_token": csrf_token},
    )
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

    signup_csrf = prime_csrf(client, "/signup?next=/today")
    request_code_response = client.post(
        "/signup",
        data={
            "action": "request_code",
            "phone_number": "010-2222-3333",
            "next": "/today",
            "csrf_token": signup_csrf,
        },
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
            "csrf_token": get_csrf_token(client),
        },
        follow_redirects=True,
    )
    login_response = login_user(
        client,
        email="member@gmail.com",
        password="pass1234",
        next_url="/today",
        follow_redirects=True,
    )
    me_response = client.get("/me")

    assert request_code_response.status_code == 200
    assert verification_code.isdigit() and len(verification_code) == 6
    assert signup_response.status_code == 200
    assert "Gmail" in signup_response.get_data(as_text=True)
    assert login_response.status_code == 200
    assert "이번 주 모델 기준안" in login_response.get_data(as_text=True)
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
    dashboard_response = login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin",
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
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin",
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
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/publish-snapshots",
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


def test_market_analysis_pages_and_api_render_handoff_data(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    app = create_app(settings)
    client = app.test_client()

    home_response = client.get("/")
    today_response = client.get("/today")
    changes_response = client.get("/changes")
    market_response = client.get("/market-analysis")
    summary_response = client.get("/api/v1/market-analysis/summary")
    detail_response = client.get("/api/v1/market-analysis/detail")
    manifest_response = client.get("/api/v1/market-analysis/manifest")

    home_body = home_response.get_data(as_text=True)
    today_body = today_response.get_data(as_text=True)
    changes_body = changes_response.get_data(as_text=True)
    market_body = market_response.get_data(as_text=True)

    assert home_response.status_code == 200
    assert today_response.status_code == 200
    assert changes_response.status_code == 200
    assert market_response.status_code == 200
    assert "시장 브리핑" in home_body
    assert "지금 시장은 이렇게 해석하고 있습니다" in home_body
    assert "공개 규칙 기반 모델 정보" in home_body
    assert "market-state-bar" in home_body
    assert "강상승" in home_body
    assert MARKET_REFERENCE_NOTE in today_body
    assert "market-state-bar" in today_body
    assert "서비스 상태" in changes_body
    assert "시장 흔들림" in market_body
    assert "시장 해석 브리핑" in market_body
    assert "ChatGPT" in market_body
    assert "Gemini" in market_body
    assert "ai_logos/chatgpt.svg" in market_body
    assert "ai_logos/gemini.svg" in market_body
    assert "추세는 살아 있지만 속도는 과열 구간이 아닙니다." in market_body
    assert "시장상태" in market_body
    assert "이전상태 대비" not in market_body
    assert "긍정 신호" in market_body
    assert "주의 신호" in market_body
    assert summary_response.status_code == 200
    assert summary_response.get_json()["data"]["state_label"] == "중립"
    assert detail_response.status_code == 200
    assert detail_response.get_json()["data"]["positive_points"][0] == "60일선 위 종목 비율 양호"
    assert manifest_response.status_code == 200
    assert manifest_response.get_json()["consumer"] == "QuantService"


def test_market_analysis_can_read_remote_handoff_json(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    remote_settings = replace(
        settings,
        market_analysis_source="remote",
        market_analysis_base_url=settings.market_analysis_dir.as_uri(),
    )
    app = create_app(remote_settings)
    client = app.test_client()

    response = client.get("/api/v1/market-analysis/summary")

    assert response.status_code == 200
    assert response.get_json()["data"]["state_label"] == "중립"


def test_market_analysis_fallback_is_graceful_when_handoff_is_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    market_response = client.get("/market-analysis")
    summary_response = client.get("/api/v1/market-analysis/summary")

    assert market_response.status_code == 200
    assert "시장 브리핑 데이터를 불러오지 못했습니다." in market_response.get_data(
        as_text=True
    ) or "시장 브리핑 데이터가 아직 준비되지 않았습니다." in market_response.get_data(as_text=True)
    assert summary_response.status_code == 503


def test_market_analysis_ai_briefs_support_partial_provider_payload(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(
        settings.market_analysis_dir,
        ai_providers=[
            {
                "provider": "chatgpt",
                "label": "ChatGPT",
                "theme_label": "시장 해석 참고",
                "enabled": True,
                "generated_at": "2026-03-23T19:00:00+09:00",
                "source": "openai:gpt-4.1-mini",
                "summary_lines": [
                    "한 줄 요약 1",
                    "한 줄 요약 2",
                    "한 줄 요약 3",
                ],
            },
            {
                "provider": "gemini",
                "label": "Gemini",
                "enabled": False,
                "generated_at": None,
                "source": "gemini:gemini-2.5-flash",
                "summary_lines": [],
            },
        ],
    )
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/market-analysis")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "시장 해석 브리핑" in body
    assert "공개 데이터 기반 해석 요약" in body
    assert "한 줄 요약 1" in body
    assert "Gemini 가 읽어주는 시장분위기" not in body


def test_market_analysis_cache_buster_preserves_existing_query_params() -> None:
    api = MarketAnalysisMockApi(build_settings(Path("D:/QuantService")))

    url = api._with_cache_buster("https://example.com/data.json?foo=bar", "123")

    assert "foo=bar" in url
    assert "ts=123" in url


def test_market_analysis_loader_rejects_mixed_asof_payloads(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    page_path = settings.market_analysis_dir / "quantservice_market_page.json"
    payload = json.loads(page_path.read_text(encoding="utf-8-sig"))
    payload["asof"] = "2026-03-23T18:00:00+09:00"
    page_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    app = create_app(settings)
    client = app.test_client()

    response = client.get("/api/v1/market-analysis/page")

    assert response.status_code == 503


def test_market_analysis_ai_briefs_placeholder_is_graceful_when_disabled(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(
        settings.market_analysis_dir,
        ai_briefs_enabled=True,
        ai_providers=[
            {
                "provider": "chatgpt",
                "label": "ChatGPT",
                "theme_label": "시장 해석 참고",
                "enabled": False,
                "generated_at": None,
                "source": "openai:gpt-4.1-mini",
                "summary_lines": [],
            },
            {
                "provider": "gemini",
                "label": "Gemini",
                "enabled": False,
                "generated_at": None,
                "source": "gemini:gemini-2.5-flash",
                "summary_lines": [],
            },
        ],
    )
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/market-analysis")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "시장 해석 브리핑" in body
    assert "시장 해석 브리핑 준비 중" in body


def test_login_rejects_missing_csrf_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    app = create_app(settings)
    app.config["ACCESS_STORE"].register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01012345678",
    )
    client = app.test_client()

    response = client.post(
        "/login",
        data={"email": "member@example.com", "password": "pass1234", "next": "/today"},
    )

    assert response.status_code == 400


def test_signup_and_feedback_reject_missing_csrf_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    signup_response = client.post(
        "/signup",
        data={"action": "request_code", "phone_number": "01011112222", "next": "/today"},
    )
    feedback_response = client.post(
        "/feedback",
        data={
            "page": "/feedback",
            "email": "user@example.com",
            "message": "충분히 긴 테스트 의견입니다.",
            "consent": "on",
        },
    )

    assert signup_response.status_code == 400
    assert feedback_response.status_code == 400


def test_billing_checkout_rejects_missing_csrf_token(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, billing_enabled=True, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    app.config["ACCESS_STORE"].register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01012345678",
    )
    client = app.test_client()

    login_user(
        client,
        email="member@example.com",
        password="pass1234",
        next_url="/pricing",
        follow_redirects=True,
    )
    response = client.post("/billing/checkout", data={"plan_id": "starter", "pay_method": "CARD"})

    assert response.status_code == 400


def test_admin_query_access_key_is_rejected_and_header_access_is_allowed(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)

    client = app.test_client()
    query_response = client.get("/admin?access_key=secret-key")
    header_response = client.get("/admin", headers={"X-Admin-Key": "secret-key"})

    assert query_response.status_code == 404
    assert header_response.status_code == 200


def test_click_tracking_ignores_untrusted_target_url(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get(
        "/e/click?ticker=005930&target=https://malicious.example/phish",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://finance.naver.com/item/main.naver?code=005930"


def test_web_app_module_import_does_not_initialize_app_or_write_db(
    tmp_path: Path, monkeypatch
) -> None:
    app_db = tmp_path / "import-app.db"
    feedback_db = tmp_path / "import-feedback.db"
    monkeypatch.setenv("APP_DB_PATH", str(app_db))
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(feedback_db))
    sys.modules.pop("service_platform.web.app", None)

    module = importlib.import_module("service_platform.web.app")

    assert hasattr(module, "create_app")
    assert not app_db.exists()
    assert not feedback_db.exists()
