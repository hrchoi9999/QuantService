import importlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from service_platform.billing.lightpay import BILLING_PLAN_PRICES
from service_platform.shared.config import Settings
from service_platform.web.app import _build_market_composite_chart_view, create_app
from service_platform.web.investment_portfolio_api import InvestmentPortfolioApi
from service_platform.web.market_analysis_api import MarketAnalysisMockApi
from service_platform.web.trading_sign_api import TradingSignSnapshotApi

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
    internal_preview_enabled: bool = False,
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
        internal_preview_enabled=internal_preview_enabled,
        analytics_preview_allowed_emails=(),
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
            "quant_model_name": "안정형 퀀트투자 모델",
            "model_definition_line": "공개 기준 기반 퀀트투자 모델",
            "model_definition_detail": (
                "변동성 완화와 자산 방어를 우선하는 모델 포트폴리오를 " "산출합니다."
            ),
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
            "quant_model_name": "균형형 퀀트투자 모델",
            "model_definition_line": "멀티애셋 데이터 기반 퀀트투자 모델",
            "model_definition_detail": (
                "주식과 ETF를 함께 담아 균형형 모델 포트폴리오를 산출합니다."
            ),
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
            "quant_model_name": "성장형 퀀트투자 모델",
            "model_definition_line": "모델 포트폴리오를 산출하는 퀀트투자 모델",
            "model_definition_detail": (
                "최근 강한 성장 주식 sleeve를 반영하는 모델 포트폴리오를 " "산출합니다."
            ),
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
            "quant_model_name": "자동전환형 퀀트투자 모델",
            "model_definition_line": "주간 브리핑용 퀀트투자 모델",
            "model_definition_detail": ("시장 상황에 따라 모델 포트폴리오를 자동으로 조정합니다."),
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
                "quant_model_name": "안정형 퀀트투자 모델",
                "model_definition_line": "공개 기준 기반 퀀트투자 모델",
                "model_definition_detail": (
                    "변동성 완화와 자산 방어를 우선하는 모델 포트폴리오를 " "산출합니다."
                ),
                "service_profile": "stable",
                "summary_text": "채권과 금 중심의 방어형 포트폴리오입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "rank_no": 1,
                        "strategy_fit_score": 0.12,
                        "strategy_fit_score_basis": "target_weight_proxy",
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
                "quant_model_name": "균형형 퀀트투자 모델",
                "model_definition_line": "멀티애셋 데이터 기반 퀀트투자 모델",
                "model_definition_detail": (
                    "주식과 ETF를 함께 담아 균형형 모델 포트폴리오를 산출합니다."
                ),
                "service_profile": "balanced",
                "summary_text": "국내 주식과 ETF를 함께 담는 균형형 포트폴리오입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "rank_no": 1,
                        "strategy_fit_score": 0.16,
                        "strategy_fit_score_basis": "target_weight_proxy",
                        "target_weight": 0.16,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "000270",
                        "asset_group": "stock",
                        "display_name": "기아",
                        "rank_no": 2,
                        "strategy_fit_score": 0.14,
                        "strategy_fit_score_basis": "target_weight_proxy",
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
                "quant_model_name": "성장형 퀀트투자 모델",
                "model_definition_line": "모델 포트폴리오를 산출하는 퀀트투자 모델",
                "model_definition_detail": (
                    "최근 강한 성장 주식 sleeve를 반영하는 모델 포트폴리오를 " "산출합니다."
                ),
                "service_profile": "growth",
                "summary_text": "최근 강한 성장 주식 sleeve를 적극적으로 반영하는 전략입니다.",
                "market_view": "중립",
                "allocation_items": [
                    {
                        "security_code": "005930",
                        "asset_group": "stock",
                        "display_name": "삼성전자",
                        "rank_no": 1,
                        "strategy_fit_score": 0.22,
                        "strategy_fit_score_basis": "target_weight_proxy",
                        "target_weight": 0.22,
                        "role_summary": "주식 코어 노출",
                        "source_type": "stock",
                    },
                    {
                        "security_code": "000660",
                        "asset_group": "stock",
                        "display_name": "SK하이닉스",
                        "rank_no": 2,
                        "strategy_fit_score": 0.18,
                        "strategy_fit_score_basis": "target_weight_proxy",
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
                "quant_model_name": "자동전환형 퀀트투자 모델",
                "model_definition_line": "주간 브리핑용 퀀트투자 모델",
                "model_definition_detail": (
                    "시장 상황에 따라 모델 포트폴리오를 자동으로 조정합니다."
                ),
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
            "quant_model_name": "안정형 퀀트투자 모델",
            "model_definition_line": "공개 기준 기반 퀀트투자 모델",
            "model_definition_detail": (
                "변동성 완화와 자산 방어를 우선하는 모델 포트폴리오를 " "산출합니다."
            ),
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
            "quant_model_name": "균형형 퀀트투자 모델",
            "model_definition_line": "멀티애셋 데이터 기반 퀀트투자 모델",
            "model_definition_detail": (
                "주식과 ETF를 함께 담아 균형형 모델 포트폴리오를 산출합니다."
            ),
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
            "quant_model_name": "성장형 퀀트투자 모델",
            "model_definition_line": "모델 포트폴리오를 산출하는 퀀트투자 모델",
            "model_definition_detail": (
                "최근 강한 성장 주식 sleeve를 반영하는 모델 포트폴리오를 " "산출합니다."
            ),
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
            "quant_model_name": "자동전환형 퀀트투자 모델",
            "model_definition_line": "주간 브리핑용 퀀트투자 모델",
            "model_definition_detail": ("시장 상황에 따라 모델 포트폴리오를 자동으로 조정합니다."),
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
                "quant_model_name": "안정형 퀀트투자 모델",
                "model_metadata": {
                    "model_display_name": "안정형 퀀트투자 모델",
                    "change_subject_name": "안정형 퀀트투자 모델",
                },
                "change_type": "rebalanced",
                "change_badge_label": "주간 모델 조정",
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
                "quant_model_name": "성장형 퀀트투자 모델",
                "service_profile": "growth",
                "change_type": "increase",
                "change_badge_label": "주간 모델 조정",
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
        "handoff_version": "2026-03-24-p2",
        "freshness": {
            "target_update_interval_minutes": 60,
            "consumer_warning_after_minutes": 90,
            "consumer_stale_after_minutes": 180,
        },
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
        "optional_files": {
            "timeline": "quantservice_market_timeline.json",
            "asset_strength": "quantservice_market_asset_strength.json",
            "state_transition": "quantservice_market_state_transition.json",
            "model_background": "quantservice_market_model_background.json",
            "timeline_history": "quantservice_market_timeline_history.json",
            "asset_strength_history": "quantservice_market_asset_strength_history.json",
            "api_timeline": "api_v1_market_analysis_timeline.json",
            "api_asset_strength": "api_v1_market_analysis_asset_strength.json",
            "api_state_transition": "api_v1_market_analysis_state_transition.json",
            "api_model_background": "api_v1_market_analysis_model_background.json",
            "api_timeline_history": "api_v1_market_analysis_timeline_history.json",
            "api_asset_strength_history": "api_v1_market_analysis_asset_strength_history.json",
            "next_day_preview": "quantservice_market_next_day_preview.json",
            "next_day_preview_manifest": "market_next_day_preview_manifest.json",
            "api_next_day_preview": "api_v1_market_analysis_next_day_preview.json",
            "analysis_tabs": "quantservice_market_analysis_tabs.json",
            "live_context": "quantservice_market_live_context.json",
            "data_guide": "quantservice_market_data_guide.json",
            "dart_summary": "quantservice_market_dart_summary.json",
            "dart_summary_history": "quantservice_market_dart_summary_history.json",
            "breadth_detail": "quantservice_market_breadth_detail.json",
            "breadth_detail_history": "quantservice_market_breadth_detail_history.json",
            "us_macro_panel": "quantservice_market_us_macro_panel.json",
            "us_macro_panel_history": "quantservice_market_us_macro_panel_history.json",
            "environment_indicators": "quantservice_market_environment_indicators.json",
            "api_environment_indicators": "api_v1_market_environment_indicators.json",
            "environment_indicators_manifest": (
                "quantservice_market_environment_indicators_manifest.json"
            ),
            "api_analysis_tabs": "api_v1_market_analysis_tabs.json",
            "api_live_context": "api_v1_market_analysis_live_context.json",
            "api_data_guide": "api_v1_market_analysis_data_guide.json",
            "api_dart_summary": "api_v1_market_analysis_dart_summary.json",
            "api_dart_summary_history": "api_v1_market_analysis_dart_summary_history.json",
            "api_breadth_detail": "api_v1_market_analysis_breadth_detail.json",
            "api_breadth_detail_history": "api_v1_market_analysis_breadth_detail_history.json",
            "api_us_macro_panel": "api_v1_market_analysis_us_macro_panel.json",
            "api_us_macro_panel_history": "api_v1_market_analysis_us_macro_panel_history.json",
        },
        "api_endpoints": {
            "timeline": "/api/v1/market-analysis/timeline?market=KR",
            "asset_strength": "/api/v1/market-analysis/asset-strength?market=KR",
            "state_transition": "/api/v1/market-analysis/state-transition?market=KR",
            "model_background": "/api/v1/market-analysis/model-background?market=KR",
            "next_day_preview": "/api/v1/market-analysis/next-day-preview?market=KR",
            "analysis_tabs": "/api/v1/market-analysis/tabs?market=KR",
            "live_context": "/api/v1/market-analysis/live-context?market=KR",
            "data_guide": "/api/v1/market-analysis/data-guide?market=KR",
            "dart_summary": "/api/v1/market-analysis/dart-summary?market=KR",
            "dart_summary_history": "/api/v1/market-analysis/dart-summary/history?market=KR",
            "breadth_detail": "/api/v1/market-analysis/breadth-detail?market=KR",
            "breadth_detail_history": "/api/v1/market-analysis/breadth-detail/history?market=KR",
            "us_macro_panel": "/api/v1/market-analysis/us-macro-panel?market=KR",
            "us_macro_panel_history": "/api/v1/market-analysis/us-macro-panel/history?market=KR",
            "environment_indicators": "/api/v1/market-environment-indicators?market=KR",
            "timeline_history": "/api/v1/market-analysis/timeline/history?market=KR",
            "asset_strength_history": "/api/v1/market-analysis/asset-strength/history?market=KR",
        },
        "data_lineage": {
            "public_rollout_phase": "market_briefing_enhancement_phase1",
        },
    }
    state_intraday_bridge = {
        "enabled": True,
        "medium_term_label": "퀀트모델 시장 흐름",
        "medium_term_description": "최근 추세와 시장 내부 신호를 반영한 퀀트모델 기준 흐름입니다.",
        "medium_term_state_label": "상승",
        "intraday_label": "오늘 장중 흐름",
        "intraday_description": "당일 지수와 breadth를 반영한 장중 흐름 참고값입니다.",
        "intraday_state_label": "강한 약세",
        "alignment": "divergent",
        "display_label": "상승 유지, 단기 조정 동반",
        "bridge_text": (
            "퀀트모델 시장 흐름은 상승이지만, 오늘 장중에는 단기 조정 흐름이 나타납니다."
        ),
        "basis_lines": [
            (
                "퀀트모델 시장 흐름 근거: 공식 지표와 내부 breadth 기준으로 퀀트투자 모델 해석에 "
                "우호적인 상승 흐름이 우세합니다."
            ),
            (
                "장중 흐름 근거: 단기 변동성과 하락 종목 비중이 커지며 참고용 약세 압력이 "
                "나타났습니다."
            ),
        ],
    }
    home = {
        "market": "KR",
        "asof": asof,
        "hero": {
            "title": "시장 브리핑",
            "subtitle": "퀀트투자 모델 해석에 필요한 시장 상태를 같은 기준으로 정리합니다.",
            "service_definition": "다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보 서비스",
            "state_label": state_label,
            "state_score": 0.2907,
            "summary_line": "추세와 방어심리가 엇갈려 뚜렷한 우세 방향은 아직 제한적입니다.",
            "change_vs_prev": "중립 -> 중립",
            "reference_note": MARKET_REFERENCE_NOTE,
            "state_intraday_bridge": state_intraday_bridge,
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
            "tone_label": "브리핑 톤",
            "reference_text": MARKET_REFERENCE_NOTE,
            "state_intraday_bridge": state_intraday_bridge,
            "compliance_meta": compliance_meta,
            "notice_block": notice_block,
        },
        "compliance_meta": compliance_meta,
        "notice_block": notice_block,
    }
    ai_briefs = {
        "enabled": ai_briefs_enabled,
        "title": "퀀트투자 모델 브리핑 참고",
        "layout": "two-column",
        "compliance_meta": compliance_meta,
        "providers": (
            ai_providers
            if ai_providers is not None
            else [
                {
                    "provider": "chatgpt",
                    "label": "ChatGPT",
                    "theme_label": "모델 해석 참고",
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
                    "theme_label": "시장 분위기 참고",
                    "enabled": True,
                    "generated_at": asof,
                    "source": "gemini:gemini-2.5-flash",
                    "summary_lines": [
                        "긍정: 시장 건강도는 양호하지만 단기 변동성은 남아 있습니다.",
                        "긍정: 중립 이상의 흐름이 유지돼 전략별 선별 대응이 유효합니다.",
                        "긍정: 지수보다 개별 강한 종목 중심 접근이 적절합니다.",
                        "긍정: 수급 개선 신호가 일부 업종에서 확인됩니다.",
                        "리스크: 환율 변동성이 단기 부담으로 남아 있습니다.",
                        "리스크: 선물 흐름이 장초반 변동성을 키울 수 있습니다.",
                        "리스크: 상승 종목 확산은 아직 제한적입니다.",
                        "리스크: 뉴스 이벤트에 따른 업종별 차별화 가능성이 있습니다.",
                    ],
                },
            ]
        ),
    }
    page = {
        "market": "KR",
        "asof": asof,
        "ai_briefs": ai_briefs,
        "page_meta": {
            "service_definition": "다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보 서비스",
            "page_title": "시장 브리핑",
            "page_subtitle": "퀀트투자 모델 해석에 필요한 시장 상태를 같은 기준으로 정리합니다.",
        },
        "service_definition": "다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보 서비스",
        "header_state": {
            "label": state_label,
            "score": 0.2907,
            "prev_label": "중립",
            "change_direction": "unchanged",
        },
        "state_intraday_bridge": state_intraday_bridge,
        "component_cards": [
            {
                "key": "trend",
                "label": "시장 추세 점검",
                "score": 0.1,
                "summary": "대형주는 버티지만 추세 확산은 아직 뚜렷하지 않습니다.",
                "description": "시장 방향은 주요 지수의 추세 강도를 요약한 참고 지표입니다.",
                "status_badge": {
                    "label": "보통",
                    "tone": "neutral",
                    "reason": "상승 흐름은 이어지지만 추세 확산은 제한적입니다.",
                },
            },
            {
                "key": "breadth",
                "label": "시장 확산 점검",
                "score": 1.9,
                "summary": "상승 흐름이 개별 종목으로 비교적 넓게 확산되고 있습니다.",
                "description": "시장 건강도는 상승 종목 확산 정도를 참고용으로 보여 줍니다.",
                "status_badge": {
                    "label": "좋음",
                    "tone": "good",
                    "reason": "상승 흐름이 비교적 넓게 확산되고 있습니다.",
                },
            },
            {
                "key": "risk",
                "label": "시장 변동성 점검",
                "score": -3.0,
                "summary": "최근 변동성과 낙폭이 커져 방어적 해석이 필요합니다.",
                "description": "시장 흔들림은 최근 변동성과 낙폭을 반영한 경계 수준입니다.",
                "status_badge": {
                    "label": "나쁨",
                    "tone": "bad",
                    "reason": "변동성 부담이 큰 편입니다.",
                },
            },
            {
                "key": "defensive_flow",
                "label": "방어자산 선호 점검",
                "score": 1.7,
                "summary": "방어 ETF 상대강도가 높지 않아 주식 선호가 상대적으로 유지됩니다.",
                "description": "방어자산 선호도는 자금 흐름이 방어 쪽으로 치우쳤는지 보여 줍니다.",
                "status_badge": {
                    "label": "좋음",
                    "tone": "good",
                    "reason": "방어자산 쏠림이 과하지 않습니다.",
                },
            },
        ],
        "signal_lists": {
            "positive_label": "모델에 우호적인 신호",
            "warning_label": "모델 해석상 주의할 신호",
            "observation_title": "이번 주 모델 해석 포인트",
            "observation_description": (
                "현재 모델 기준안을 읽을 때 함께 보면 좋은 시장 브리핑 관찰 포인트입니다."
            ),
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
        "usage_guide_card": {
            "title": "이 시장 브리핑은 어디에 쓰이나요?",
            "body": [
                "전략별 퀀트모델을 읽을 때 함께 참고하는 공개 브리핑입니다.",
                "시장 상태와 모델 포트폴리오 해석을 같은 기준으로 보는 데 도움이 됩니다.",
            ],
        },
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
    timeline = {
        "market": "KR",
        "asof": asof,
        "title": "상태 타임라인",
        "description": (
            "최근 시장상태와 핵심 점수 흐름을 시간순으로 정리한 " "공개 브리핑 데이터입니다."
        ),
        "current_state": {
            "asof": asof,
            "state_label": state_label,
            "state_score": 0.2907,
            "trend_score": 0.1,
            "breadth_score": 1.9,
            "risk_score": -3.0,
            "defensive_flow_score": 1.7,
            "total_score": 0.2907,
        },
        "trend_direction": "unchanged",
        "points": [
            {
                "asof": "2026-03-23T15:00:00+09:00",
                "state_label": "약보합",
                "state_score": -0.2,
                "trend_score": -0.1,
                "breadth_score": 0.8,
                "risk_score": -2.0,
                "defensive_flow_score": 1.0,
                "total_score": -0.2,
            },
            {
                "asof": "2026-03-23T17:00:00+09:00",
                "state_label": state_label,
                "state_score": 0.2907,
                "trend_score": 0.1,
                "breadth_score": 1.9,
                "risk_score": -3.0,
                "defensive_flow_score": 1.7,
                "total_score": 0.2907,
            },
        ],
    }
    asset_strength = {
        "market": "KR",
        "asof": asof,
        "title": "자산군 상대강도",
        "description": (
            "주요 자산군의 최근 상대 흐름을 비교해 현재 어떤 자산이 "
            "상대적으로 강한지 보여 줍니다."
        ),
        "assets": [
            {
                "asset_group": "KOSPI",
                "ret_20d": 0.0388,
                "strength_score": 2.10,
                "strength_rank": 1,
                "strength_label": "강함",
            },
            {
                "asset_group": "KOSDAQ",
                "ret_20d": 0.0321,
                "strength_score": 0.27,
                "strength_rank": 2,
                "strength_label": "중립",
            },
            {
                "asset_group": "GOLD",
                "ret_20d": -0.018,
                "strength_score": -0.81,
                "strength_rank": 6,
                "strength_label": "약함",
            },
        ],
        "top_assets": [
            {"asset_group": "KOSPI"},
            {"asset_group": "KOSDAQ"},
        ],
        "bottom_assets": [
            {"asset_group": "GOLD"},
            {"asset_group": "BOND"},
        ],
    }
    timeline_history = {
        "source_name": "QuantMarket",
        "schema_version": "market_timeline_history.v1",
        "as_of_date": asof,
        "generated_at": asof,
        "series": [
            {
                "asof": "2026-03-23T15:00:00+09:00",
                "total_score": -0.2,
                "trend_score": -0.1,
                "breadth_score": 0.8,
                "risk_score": -2.0,
                "defensive_flow_score": 1.0,
                "state_label": "약보합",
            },
            {
                "asof": "2026-03-23T17:00:00+09:00",
                "total_score": 0.29,
                "trend_score": 0.1,
                "breadth_score": 1.9,
                "risk_score": -3.0,
                "defensive_flow_score": 1.7,
                "state_label": state_label,
            },
            {
                "asof": asof,
                "total_score": 1.52,
                "trend_score": 1.2,
                "breadth_score": 2.1,
                "risk_score": -0.8,
                "defensive_flow_score": 0.7,
                "state_label": "상승",
            },
        ],
    }
    asset_strength_history = {
        "source_name": "QuantMarket",
        "schema_version": "market_asset_strength_history.v1",
        "as_of_date": asof,
        "generated_at": asof,
        "series": [
            {
                "asof": "2026-03-23T15:00:00+09:00",
                "asset_group": "KOSPI",
                "strength_score": 1.2,
                "ret_20d": 0.02,
                "strength_rank": 1,
                "strength_label": "강함",
            },
            {
                "asof": asof,
                "asset_group": "KOSPI",
                "strength_score": 2.4,
                "ret_20d": 0.052,
                "strength_rank": 1,
                "strength_label": "강함",
            },
            {
                "asof": asof,
                "asset_group": "KOSDAQ",
                "strength_score": 0.4,
                "ret_20d": 0.021,
                "strength_rank": 2,
                "strength_label": "중립",
            },
            {
                "asof": asof,
                "asset_group": "GOLD",
                "strength_score": -0.9,
                "ret_20d": -0.014,
                "strength_rank": 3,
                "strength_label": "약함",
            },
        ],
    }
    state_transition = {
        "market": "KR",
        "asof": asof,
        "title": "상태 전이 요약",
        "description": (
            "현재 상태가 얼마나 이어지고 있는지와 최근 상태 변화 빈도를 "
            "요약한 공개 브리핑 데이터입니다."
        ),
        "current": {
            "current_state": "상승",
            "prev_state": "중립",
            "duration_hours": 31.1,
            "transition_count_5d": 4,
            "transition_count_20d": 4,
            "stability_score": 0.76,
        },
        "recent_changes": [
            {
                "asof": asof,
                "state_label": "상승",
                "prev_state_label": "중립",
                "state_change_direction": "stronger",
                "state_score": 0.2907,
            },
            {
                "asof": "2026-03-23T16:00:00+09:00",
                "state_label": "중립",
                "prev_state_label": "약보합",
                "state_change_direction": "unchanged",
                "state_score": -0.12,
            },
        ],
    }
    model_background = {
        "market": "KR",
        "asof": asof,
        "title": "모델 해석 백그라운드",
        "description": "현재 시장브리핑을 모델 기준안과 연결해서 읽기 위한 공개 배경 데이터입니다.",
        "briefing_tone": "중립 해석 환경",
        "summary_line": "공개 지표 기준으로 퀀트투자 모델 해석에 참고할 시장 흐름을 요약했습니다.",
        "reference_note": MARKET_REFERENCE_NOTE,
        "model_background_points": [
            "공개 지표 기준으로 퀀트투자 모델 해석에 참고할 시장 흐름을 요약했습니다.",
            "20일선 위 종목 비율과 변동성 지표를 함께 볼 필요가 있습니다.",
            "현재 상태 지속 시간은 31.1시간입니다.",
        ],
        "favorable_signals": ["60일선 위 종목 비율 양호", "코스피 1개월 상승 흐름"],
        "caution_signals": ["20일선 위 종목 비율 낮음", "변동성 확대"],
    }
    api_timeline = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/timeline?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": timeline,
    }
    api_asset_strength = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/asset-strength?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": asset_strength,
    }
    api_timeline_history = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/timeline/history?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": timeline_history,
    }
    api_asset_strength_history = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/asset-strength/history?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": asset_strength_history,
    }
    api_state_transition = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/state-transition?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": state_transition,
    }
    api_model_background = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/model-background?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": model_background,
    }

    next_day_preview = {
        "market": "KR",
        "asof": asof,
        "active_now": True,
        "active_window": "2026-03-23 18:00 KST ~ 2026-03-24 09:00 KST",
        "reference_session": "2026-03-24 장초반 참고",
        "display_title": "내일 시장 전망 참고",
        "display_subtitle": "장마감 이후 공개 데이터 기준 참고 레이어",
        "preview_label": "혼조 출발 가능성",
        "preview_score": -0.12,
        "headline_line": "해외 야간 흐름과 단기 변동성을 감안하면 혼조 출발 가능성이 있습니다.",
        "summary_line": "기존 상태 레이어를 대체하지 않는 보조 참고 레이어입니다.",
        "supporting_points": [
            "야간 지수 흐름은 방향성이 뚜렷하지 않아 장초반 혼조 가능성을 시사합니다.",
            "달러와 금리 변동성이 남아 있어 개장 초반 체감 부담이 커질 수 있습니다.",
        ],
        "risk_points": [
            "대형주 약세가 이어지면 장초반 부담이 확대될 수 있습니다.",
            "변동성 재확대 시 오전 중 방향 전환 가능성도 열려 있습니다.",
        ],
        "overnight_assets": [
            {
                "asset_code": "KOSPI200_NIGHT_FUT",
                "asset_name": "KOSPI200 선물(야간 포함)",
                "asset_group": "kr_futures",
                "change_pct": 0.0042,
                "price": 355.2,
                "source": "naver:night_fut",
                "is_fallback": False,
            },
            {
                "asset_code": "KOREA_PROXY_EWY",
                "asset_name": "한국 관련 야간 프록시(EWY)",
                "asset_group": "korea_proxy",
                "change_pct": 0.0033,
                "price": 70.2,
                "source": "yahoo:EWY",
                "is_fallback": False,
            },
            {
                "asset_code": "SP500_FUT",
                "asset_name": "S&P500 선물",
                "asset_group": "us_futures",
                "change_pct": 0.003,
                "price": 5200.0,
                "source": "yahoo:ES=F",
                "is_fallback": False,
            },
            {
                "asset_code": "USDKRW",
                "asset_name": "USD/KRW",
                "asset_group": "fx",
                "change_pct": 0.0012,
                "price": 1340.0,
                "source": "yahoo:KRW=X",
                "is_fallback": False,
            },
        ],
        "market_flow_label": "중립",
        "market_flow_score": 0.08,
        "market_flow_reference_note": (
            "내일 시장 참고 레이어이며 기존 시장 상태를 대체하지 않습니다."
        ),
        "content_hash": "preview-hash-001",
        "material_change_flag": True,
        "notice_block": {
            "short_notice": (
                "내일 시장 참고용으로만 제공되는 공개 브리핑이며 특정 행동을 안내하지 않습니다."
            )
        },
        "compliance_meta": compliance_meta,
    }
    next_day_preview_manifest = {
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "consumer": "QuantService",
        "content_hash": "preview-hash-001",
        "active_now": True,
        "active_window": "2026-03-23 18:00 KST ~ 2026-03-24 09:00 KST",
    }
    api_next_day_preview = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/next-day-preview?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": next_day_preview,
    }
    analysis_tabs = {
        "market": "KR",
        "asof": asof,
        "tabs": [
            {"key": "state", "label": "시장 상태", "description": "상태점수와 구성요소"},
            {"key": "assets", "label": "자산 강도", "description": "상대강도와 순위 변화"},
            {"key": "live", "label": "장중/야간 참고", "description": "장중과 야간 레이어"},
            {"key": "guide", "label": "데이터 해설", "description": "지표 의미와 데이터 성격"},
        ],
    }
    live_context = {
        "market": "KR",
        "asof": asof,
        "display_title": "장중/야간 참고",
        "summary_line": "장중 데이터와 종가 기준 데이터는 서로 다른 참고 레이어입니다.",
        "cards": [
            {
                "title": "오늘 장중 흐름",
                "state_label": "강한 약세",
                "description": "당일 지수와 breadth를 반영한 참고 흐름입니다.",
            },
            {
                "title": "퀀트모델 시장 흐름",
                "state_label": "상승",
                "description": "전일 종가 기준 공식 흐름입니다.",
            },
        ],
    }
    data_guide = {
        "market": "KR",
        "asof": asof,
        "display_title": "데이터 해설",
        "summary_line": "시장 분석에 사용되는 지표의 의미와 데이터 성격을 설명합니다.",
        "sections": [
            {
                "title": "official",
                "description": "공식 원천에서 확인되는 종가 기준 데이터입니다.",
                "lines": ["상태점수와 구성요소는 공개형 시장 분석에만 사용됩니다."],
            },
            {
                "title": "proxy",
                "description": "직접 원천이 없을 때 사용하는 대체 참고 지표입니다.",
                "lines": ["장중/야간 참고는 기존 시장 상태를 대체하지 않습니다."],
            },
        ],
    }
    api_analysis_tabs = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/tabs?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": analysis_tabs,
    }
    api_live_context = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/live-context?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": live_context,
    }
    api_data_guide = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/data-guide?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": data_guide,
    }
    dart_summary = {
        "market": "KR",
        "asof": asof,
        "enabled": True,
        "reference_date": "2026-04-29",
        "filing_count_total": 128,
        "market_breakdown": {
            "kospi_count": 48,
            "kosdaq_count": 80,
        },
        "risk_event_count": 7,
        "filing_count_by_type": [
            {"type": "funding", "label": "자금조달", "count": 9},
            {"type": "shareholder", "label": "주주/지분", "count": 13},
            {"type": "earnings", "label": "실적", "count": 22},
            {"type": "governance", "label": "지배구조", "count": 4},
            {"type": "general", "label": "일반", "count": 80},
        ],
        "highlights": [
            {
                "corp_name": "예시기업",
                "title": "주요사항보고서",
                "filing_date": "2026-04-29",
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260429000001",
            }
        ],
        "recent_filings": [
            {
                "corp_name": "예시기업",
                "title": "사업보고서",
                "filing_date": "2026-04-29",
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260429000002",
            },
            {
                "corp_name": "다른기업",
                "title": "분기보고서",
                "filing_date": "2026-04-29",
            },
        ],
    }
    dart_summary_history = {
        "market": "KR",
        "asof": asof,
        "series": [
            {
                "asof": "2026-04-28T18:00:00+09:00",
                "reference_date": "2026-04-28",
                "filing_count_total": 112,
                "kospi_count": 42,
                "kosdaq_count": 70,
                "risk_event_count": 5,
                "funding_count": 6,
                "shareholder_count": 11,
                "earnings_count": 20,
                "governance_count": 3,
                "general_count": 72,
            },
            {
                "asof": "2026-04-29T18:00:00+09:00",
                "reference_date": "2026-04-29",
                "filing_count_total": 128,
                "kospi_count": 48,
                "kosdaq_count": 80,
                "risk_event_count": 7,
                "funding_count": 9,
                "shareholder_count": 13,
                "earnings_count": 22,
                "governance_count": 4,
                "general_count": 80,
            },
        ],
    }
    api_dart_summary = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/dart-summary?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": dart_summary,
    }
    api_dart_summary_history = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/dart-summary/history?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": dart_summary_history,
    }
    breadth_detail = {
        "market": "KR",
        "asof": asof,
        "summary": {
            "latest_close_asof": "2026-04-29",
            "latest_intraday_asof": "2026-04-29T14:30:00+09:00",
        },
    }
    breadth_detail_history = {
        "market": "KR",
        "asof": asof,
        "summary": {
            "latest_close_asof": "2026-04-29",
            "latest_intraday_asof": "2026-04-29T14:30:00+09:00",
            "close_points": 2,
            "intraday_points": 4,
        },
        "close_series": [
            {
                "asof": "2026-04-28",
                "above_20dma_ratio": 0.42,
                "above_60dma_ratio": 0.61,
                "adv_dec_ratio": 0.92,
                "new_high_count": 12,
                "new_low_count": 8,
                "breadth_regime_label": "중립",
            },
            {
                "asof": "2026-04-29",
                "above_20dma_ratio": 0.48,
                "above_60dma_ratio": 0.64,
                "adv_dec_ratio": 1.18,
                "new_high_count": 18,
                "new_low_count": 6,
                "breadth_regime_label": "개선",
            },
        ],
        "intraday_series": [
            {
                "asof": "2026-04-29T10:00:00+09:00",
                "session_date": "2026-04-29",
                "universe_code": "KOSPI",
                "positive_ratio": 0.45,
                "adv_dec_ratio": 0.98,
                "status_label": "중립",
            },
            {
                "asof": "2026-04-29T14:30:00+09:00",
                "session_date": "2026-04-29",
                "universe_code": "KOSPI",
                "positive_ratio": 0.54,
                "adv_dec_ratio": 1.2,
                "status_label": "개선",
            },
            {
                "asof": "2026-04-29T10:00:00+09:00",
                "session_date": "2026-04-29",
                "universe_code": "KOSDAQ",
                "positive_ratio": 0.38,
                "adv_dec_ratio": 0.84,
                "status_label": "약세",
            },
            {
                "asof": "2026-04-29T14:30:00+09:00",
                "session_date": "2026-04-29",
                "universe_code": "KOSDAQ",
                "positive_ratio": 0.49,
                "adv_dec_ratio": 1.02,
                "status_label": "중립",
            },
        ],
    }
    us_macro_panel = {
        "market": "KR",
        "asof": asof,
        "headline_line": "야간 글로벌 지표는 혼조권에서 움직였습니다.",
    }
    us_macro_panel_history = {
        "market": "KR",
        "asof": asof,
        "summary": {
            "latest_asset_asof": "2026-04-29T07:00:00+09:00",
            "latest_preview_asof": "2026-04-29T07:10:00+09:00",
            "asset_points": 12,
            "preview_points": 2,
        },
        "asset_series": [
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "KOREA_PROXY_EWY",
                "asset_name": "한국 관련 야간 프록시(EWY)",
                "change_pct": 0.002,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "KOREA_PROXY_EWY",
                "asset_name": "한국 관련 야간 프록시(EWY)",
                "change_pct": 0.004,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "SP500_FUT",
                "asset_name": "S&P500 선물",
                "change_pct": -0.001,
                "status_label": "하락",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "SP500_FUT",
                "asset_name": "S&P500 선물",
                "change_pct": 0.003,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "NASDAQ100_FUT",
                "asset_name": "나스닥100 선물",
                "change_pct": -0.002,
                "status_label": "하락",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "NASDAQ100_FUT",
                "asset_name": "나스닥100 선물",
                "change_pct": 0.005,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "USDKRW",
                "asset_name": "USD/KRW",
                "change_pct": 0.001,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "USDKRW",
                "asset_name": "USD/KRW",
                "change_pct": -0.001,
                "status_label": "하락",
            },
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "WTI",
                "asset_name": "WTI",
                "change_pct": 0.006,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "WTI",
                "asset_name": "WTI",
                "change_pct": 0.002,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-28T07:00:00+09:00",
                "asset_code": "US10Y",
                "asset_name": "미국 10년 금리",
                "change_pct": 0.0008,
                "status_label": "상승",
            },
            {
                "asof": "2026-04-29T07:00:00+09:00",
                "asset_code": "US10Y",
                "asset_name": "미국 10년 금리",
                "change_pct": -0.0005,
                "status_label": "하락",
            },
        ],
        "preview_series": [
            {
                "asof": "2026-04-28T07:10:00+09:00",
                "reference_session": "2026-04-28",
                "preview_label": "혼조",
                "preview_score": -0.1,
                "overnight_futures_bias": -0.2,
                "global_risk_bias": 0.1,
                "overnight_fx_bias": 0.05,
            },
            {
                "asof": "2026-04-29T07:10:00+09:00",
                "reference_session": "2026-04-29",
                "preview_label": "우호",
                "preview_score": 0.24,
                "overnight_futures_bias": 0.3,
                "global_risk_bias": 0.12,
                "overnight_fx_bias": -0.04,
                "headline_line": "야간 글로벌 지표는 혼조권에서 움직였습니다.",
            },
        ],
    }
    api_breadth_detail = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/breadth-detail?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": breadth_detail,
    }
    api_breadth_detail_history = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/breadth-detail/history?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": breadth_detail_history,
    }
    api_us_macro_panel = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/us-macro-panel?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": us_macro_panel,
    }
    api_us_macro_panel_history = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-analysis/us-macro-panel/history?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": us_macro_panel_history,
    }
    environment_indicators = {
        "market": "KR",
        "asof": asof,
        "generated_at": asof,
        "timezone": "Asia/Seoul",
        "title": "시장 환경 지표",
        "description": "국내 지수와 환율, 미국 금리와 글로벌 ETF 흐름을 정리합니다.",
        "chart_policy": {
            "default_chart_height_px": 160,
            "popup_chart_height_px": 420,
        },
        "sections": [
            {
                "section_key": "domestic_source",
                "title": "국내 시장 원천 데이터",
                "coverage_warning": "일부 원천 데이터는 지연될 수 있습니다.",
                "series": [
                    {
                        "series_id": "kospi_close",
                        "display_name_kr": "KOSPI 종가",
                        "category_label_kr": "국내 지수",
                        "source_provider": "KRX",
                        "source_detail": "KOSPI",
                        "unit": "pt",
                        "frequency": "daily",
                        "period_label": "최근 3년",
                        "latest_date": "2026-04-29",
                        "latest_value": 2540.12,
                        "row_count": 2,
                        "chart_type": "line",
                        "default_chart_height_px": 160,
                        "popup_enabled": True,
                        "points": [
                            {"date": "2026-04-28", "value": 2520.4},
                            {"date": "2026-04-29", "value": 2540.12},
                        ],
                    }
                ],
            },
            {
                "section_key": "fred_macro",
                "title": "FRED 매크로/금리 데이터",
                "series": [
                    {
                        "series_id": "dgs10",
                        "display_name_kr": "미국 10년 금리",
                        "category_label_kr": "금리",
                        "source_provider": "FRED",
                        "source_detail": "DGS10",
                        "unit": "%",
                        "frequency": "daily",
                        "period_label": "최근 3년",
                        "latest_date": "2026-04-29",
                        "latest_value": 4.21,
                        "row_count": 2,
                        "chart_type": "line",
                        "points": [
                            {"date": "2026-04-28", "value": 4.18},
                            {"date": "2026-04-29", "value": 4.21},
                        ],
                    }
                ],
            },
            {
                "section_key": "yahoo_global",
                "title": "Yahoo 글로벌 시장 데이터",
                "series": [
                    {
                        "series_id": "spy",
                        "display_name_kr": "SPY ETF",
                        "category_label_kr": "글로벌 ETF",
                        "source_provider": "Yahoo",
                        "source_detail": "SPY",
                        "unit": "USD",
                        "frequency": "daily",
                        "period_label": "최근 3년",
                        "latest_date": "2026-04-29",
                        "latest_value": 520.3,
                        "row_count": 2,
                        "chart_type": "line",
                        "points": [
                            {"date": "2026-04-28", "value": 518.1},
                            {"date": "2026-04-29", "value": 520.3},
                        ],
                    }
                ],
            },
        ],
        "notice_block": {
            "title": "주의사항",
            "body": ["본 정보는 공개 시장 데이터 흐름을 보여주는 참고 자료입니다."],
        },
    }
    api_environment_indicators = {
        "api_version": "v1",
        "endpoint": "/api/v1/market-environment-indicators?market=KR",
        "market": "KR",
        "asof": asof,
        "generated_by": "QuantMarket",
        "data": environment_indicators,
    }
    environment_indicators_manifest = {
        "market": "KR",
        "asof": asof,
        "generated_at": asof,
        "files": {
            "page": "quantservice_market_environment_indicators.json",
            "api": "api_v1_market_environment_indicators.json",
        },
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
        "quantservice_market_timeline.json": timeline,
        "quantservice_market_asset_strength.json": asset_strength,
        "quantservice_market_timeline_history.json": timeline_history,
        "quantservice_market_asset_strength_history.json": asset_strength_history,
        "quantservice_market_state_transition.json": state_transition,
        "quantservice_market_model_background.json": model_background,
        "api_v1_market_analysis_timeline.json": api_timeline,
        "api_v1_market_analysis_asset_strength.json": api_asset_strength,
        "api_v1_market_analysis_timeline_history.json": api_timeline_history,
        "api_v1_market_analysis_asset_strength_history.json": api_asset_strength_history,
        "api_v1_market_analysis_state_transition.json": api_state_transition,
        "api_v1_market_analysis_model_background.json": api_model_background,
        "quantservice_market_next_day_preview.json": next_day_preview,
        "market_next_day_preview_manifest.json": next_day_preview_manifest,
        "api_v1_market_analysis_next_day_preview.json": api_next_day_preview,
        "quantservice_market_analysis_tabs.json": analysis_tabs,
        "quantservice_market_live_context.json": live_context,
        "quantservice_market_data_guide.json": data_guide,
        "quantservice_market_dart_summary.json": dart_summary,
        "quantservice_market_dart_summary_history.json": dart_summary_history,
        "quantservice_market_breadth_detail.json": breadth_detail,
        "quantservice_market_breadth_detail_history.json": breadth_detail_history,
        "quantservice_market_us_macro_panel.json": us_macro_panel,
        "quantservice_market_us_macro_panel_history.json": us_macro_panel_history,
        "quantservice_market_environment_indicators.json": environment_indicators,
        "api_v1_market_environment_indicators.json": api_environment_indicators,
        "quantservice_market_environment_indicators_manifest.json": (
            environment_indicators_manifest
        ),
        "api_v1_market_analysis_tabs.json": api_analysis_tabs,
        "api_v1_market_analysis_live_context.json": api_live_context,
        "api_v1_market_analysis_data_guide.json": api_data_guide,
        "api_v1_market_analysis_dart_summary.json": api_dart_summary,
        "api_v1_market_analysis_dart_summary_history.json": api_dart_summary_history,
        "api_v1_market_analysis_breadth_detail.json": api_breadth_detail,
        "api_v1_market_analysis_breadth_detail_history.json": api_breadth_detail_history,
        "api_v1_market_analysis_us_macro_panel.json": api_us_macro_panel,
        "api_v1_market_analysis_us_macro_panel_history.json": api_us_macro_panel_history,
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


def get_login_email_verification_code(client) -> str:
    with client.session_transaction() as session_state:
        payload = session_state.get("pending_login_email_verification") or {}
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
    home_body = home_response.get_data(as_text=True)
    assert "시장 브리핑" in home_body
    assert "market-state-bar" in home_body
    assert "안정형 모델" not in home_body
    assert "변경 내역" not in home_body
    assert today_response.status_code == 200
    today_body = today_response.get_data(as_text=True)
    assert "주식 sleeve 비중" in today_body
    assert "ETF sleeve 비중" in today_body
    assert "현금성 비중" in today_body
    assert "전략별 퀀트모델" in today_body
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

    assert performance_response.status_code == 404

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

    models_response = client.get("/api/v1/model-catalog")
    legacy_models_response = client.get("/api/v1/user-models")
    today_response = client.get("/api/v1/model-snapshots/today")
    weekly_today_response = client.get("/api/v1/model-weekly/today")
    legacy_today_response = client.get("/api/v1/recommendation/today")
    profile_response = client.get("/api/v1/model-snapshots/stable")
    auto_profile_response = client.get("/api/v1/model-snapshots/auto")
    weekly_profile_response = client.get("/api/v1/model-weekly/stable")
    legacy_profile_response = client.get("/api/v1/recommendation/stable")
    performance_response = client.get("/api/v1/performance/summary")
    performance_alias_response = client.get("/api/v1/model-performance/summary")
    changes_response = client.get("/api/v1/changes/recent")
    manifest_response = client.get("/api/v1/publish-status")
    manifest_alias_response = client.get("/api/v1/manifest")

    assert models_response.status_code == 200
    assert legacy_models_response.status_code == 404
    assert models_response.get_json()["models"][0]["user_model_name"] == "안정형"
    assert len(models_response.get_json()["models"]) == 3
    assert all(model["service_profile"] != "auto" for model in models_response.get_json()["models"])
    assert today_response.status_code == 200
    assert weekly_today_response.status_code == 200
    assert legacy_today_response.status_code == 404
    assert today_response.get_json()["reports"][0]["service_profile"] == "stable"
    assert len(today_response.get_json()["reports"]) == 3
    assert all(
        report["service_profile"] != "auto" for report in today_response.get_json()["reports"]
    )
    assert weekly_today_response.get_json() == today_response.get_json()
    assert "target_user_type" not in today_response.get_json()["reports"][0]
    assert profile_response.status_code == 200
    assert auto_profile_response.status_code == 404
    assert weekly_profile_response.status_code == 200
    assert legacy_profile_response.status_code == 404
    assert profile_response.get_json()["report"]["user_model_name"] == "안정형"
    assert weekly_profile_response.get_json() == profile_response.get_json()
    assert "target_user_type" not in profile_response.get_json()["report"]
    assert performance_response.status_code == 200
    assert performance_alias_response.status_code == 200
    assert performance_alias_response.get_json() == performance_response.get_json()
    assert len(performance_response.get_json()["models"]) == 3
    assert all(
        model["service_profile"] != "auto" for model in performance_response.get_json()["models"]
    )
    assert changes_response.status_code == 200
    assert changes_response.get_json()["changes"][0]["service_profile"] == "stable"
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
    body = response.get_data(as_text=True)
    assert "서비스 이용권 안내" in body
    assert "개별 투자자문 계약이 아닙니다." in body
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
    assert "전략별 퀀트모델" in login_response.get_data(as_text=True)
    assert me_response.get_json()["phone_verification_status"] == "verified"
    assert me_response.get_json()["auth_provider"] == "local"


def test_login_can_require_email_verification_code(tmp_path: Path) -> None:
    settings = replace(
        build_settings(tmp_path, trial_mode=True),
        login_email_verification_enabled=True,
        login_email_verification_preview_enabled=True,
    )
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01022223333",
    )
    client = app.test_client()

    csrf_token = prime_csrf(client, "/login?next=/today")
    password_response = client.post(
        "/login",
        data={
            "action": "password",
            "email": "member@example.com",
            "password": "pass1234",
            "next": "/today",
            "csrf_token": csrf_token,
        },
        follow_redirects=True,
    )
    verification_code = get_login_email_verification_code(client)
    verify_response = client.post(
        "/login",
        data={
            "action": "verify_email_code",
            "email_verification_code": verification_code,
            "next": "/today",
            "csrf_token": get_csrf_token(client),
        },
        follow_redirects=True,
    )

    assert password_response.status_code == 200
    assert "이메일 인증" in password_response.get_data(as_text=True)
    assert verification_code.isdigit() and len(verification_code) == 6
    assert verify_response.status_code == 200
    assert "전략별 퀀트모델" in verify_response.get_data(as_text=True)
    with client.session_transaction() as session_state:
        assert session_state.get("user_id")
        assert "pending_login_email_verification" not in session_state


def test_login_stale_email_verification_post_redirects_when_already_authenticated(
    tmp_path: Path,
) -> None:
    settings = replace(
        build_settings(tmp_path, trial_mode=True),
        login_email_verification_enabled=True,
        login_email_verification_preview_enabled=True,
    )
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01022223333",
    )
    client = app.test_client()

    csrf_token = prime_csrf(client, "/login?next=/today")
    client.post(
        "/login",
        data={
            "action": "password",
            "email": "member@example.com",
            "password": "pass1234",
            "next": "/today",
            "csrf_token": csrf_token,
        },
    )
    verification_code = get_login_email_verification_code(client)
    stale_csrf_token = get_csrf_token(client)
    verify_payload = {
        "action": "verify_email_code",
        "email_verification_code": verification_code,
        "next": "/today",
        "csrf_token": stale_csrf_token,
    }

    first_response = client.post("/login", data=verify_payload, follow_redirects=False)
    second_response = client.post("/login", data=verify_payload, follow_redirects=False)

    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert second_response.headers["Location"].endswith("/today")


def test_login_email_verification_sends_smtp_message(tmp_path: Path, monkeypatch) -> None:
    settings = replace(
        build_settings(tmp_path, trial_mode=True),
        login_email_verification_enabled=True,
        login_email_verification_mode="smtp",
        login_email_verification_preview_enabled=False,
        login_email_verification_smtp_username="admin@koreascf.com",
        login_email_verification_smtp_password="secret",
        login_email_verification_from_email="admin@koreascf.com",
    )
    seed_user_snapshot(settings.user_snapshot_dir)
    sent_messages = []

    def fake_send_login_verification_email(*, settings, to_email, code):
        sent_messages.append(
            {
                "mode": settings.login_email_verification_mode,
                "to_email": to_email,
                "code": code,
            }
        )

    monkeypatch.setattr(
        "service_platform.web.app.send_login_verification_email",
        fake_send_login_verification_email,
    )
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01022223333",
    )
    client = app.test_client()

    csrf_token = prime_csrf(client, "/login?next=/today")
    response = client.post(
        "/login",
        data={
            "action": "password",
            "email": "member@example.com",
            "password": "pass1234",
            "next": "/today",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert sent_messages
    assert sent_messages[0]["mode"] == "smtp"
    assert sent_messages[0]["to_email"] == "member@example.com"
    assert sent_messages[0]["code"].isdigit()


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


def test_production_settings_force_remote_snapshot_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SNAPSHOT_SOURCE", raising=False)
    monkeypatch.delenv("SNAPSHOT_GCS_BASE_URL", raising=False)

    config_module = importlib.import_module("service_platform.shared.config")
    config_module = importlib.reload(config_module)
    settings = config_module.get_settings()

    assert settings.snapshot_source == "remote"
    assert (
        settings.snapshot_gcs_base_url
        == "https://storage.googleapis.com/quantservice-489808-market-analysis"
    )


def test_production_settings_override_local_snapshot_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SNAPSHOT_SOURCE", "local")
    monkeypatch.setenv("SNAPSHOT_GCS_BASE_URL", "")

    config_module = importlib.import_module("service_platform.shared.config")
    config_module = importlib.reload(config_module)
    settings = config_module.get_settings()

    assert settings.snapshot_source == "remote"
    assert (
        settings.snapshot_gcs_base_url
        == "https://storage.googleapis.com/quantservice-489808-market-analysis"
    )


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
    market_data_response = client.get("/market-analysis/data")
    summary_response = client.get("/api/v1/market-analysis/summary")
    detail_response = client.get("/api/v1/market-analysis/detail")
    timeline_response = client.get("/api/v1/market-analysis/timeline")
    asset_strength_response = client.get("/api/v1/market-analysis/asset-strength")
    timeline_history_response = client.get("/api/v1/market-analysis/timeline/history")
    asset_strength_history_response = client.get("/api/v1/market-analysis/asset-strength/history")
    state_transition_response = client.get("/api/v1/market-analysis/state-transition")
    model_background_response = client.get("/api/v1/market-analysis/model-background")
    next_day_preview_response = client.get("/api/v1/market-analysis/next-day-preview")
    tabs_response = client.get("/api/v1/market-analysis/tabs")
    live_context_response = client.get("/api/v1/market-analysis/live-context")
    data_guide_response = client.get("/api/v1/market-analysis/data-guide")
    dart_summary_response = client.get("/api/v1/market-analysis/dart-summary")
    dart_summary_history_response = client.get("/api/v1/market-analysis/dart-summary/history")
    breadth_detail_response = client.get("/api/v1/market-analysis/breadth-detail")
    breadth_detail_history_response = client.get("/api/v1/market-analysis/breadth-detail/history")
    us_macro_panel_response = client.get("/api/v1/market-analysis/us-macro-panel")
    us_macro_panel_history_response = client.get("/api/v1/market-analysis/us-macro-panel/history")
    environment_response = client.get("/market-environment-indicators")
    environment_api_response = client.get("/api/v1/market-environment-indicators")
    manifest_response = client.get("/api/v1/market-analysis/manifest")

    home_body = home_response.get_data(as_text=True)
    today_body = today_response.get_data(as_text=True)
    changes_body = changes_response.get_data(as_text=True)
    market_body = market_response.get_data(as_text=True)
    market_data_body = market_data_response.get_data(as_text=True)
    environment_body = environment_response.get_data(as_text=True)

    assert home_response.status_code == 200
    assert today_response.status_code == 200
    assert changes_response.status_code == 200
    assert market_response.status_code == 200
    assert market_data_response.status_code == 200
    assert environment_response.status_code == 200
    assert "시장 분석" in home_body
    assert "시장 환경 지표" in home_body
    assert "시장 환경 지표" in environment_body
    assert "국내 시장 원천 데이터" in environment_body
    assert "FRED 매크로/금리 데이터" in environment_body
    assert "Yahoo 글로벌 시장 데이터" in environment_body
    assert "KOSPI 종가" in environment_body
    assert "미국 10년 금리" in environment_body
    assert "SPY ETF" in environment_body
    assert "data-environment-chart-card" in environment_body
    assert "시장 분석" in market_data_body
    assert "시장 흐름" in market_data_body
    assert "market-state-bar" in market_data_body
    assert "시장 상태" not in market_data_body
    assert "자산 강도" not in market_data_body
    assert "장중/야간 참고" not in market_data_body
    assert "데이터 해설" not in market_data_body
    assert "상태점수 timeline" not in market_data_body
    assert "강도 순위 변화" not in market_data_body
    assert "내일 시장 전망 참고" not in market_data_body
    assert "DART 공시 흐름" in market_data_body
    assert "2026-04-29" in market_data_body
    assert "전체 공시" in market_data_body
    assert "리스크 공시" in market_data_body
    assert "공시 원문 보기" in market_data_body
    assert "시장 내부 확산 흐름" in market_data_body
    assert "20일선 위 종목 비율" in market_data_body
    assert "60일선 위 종목 비율" in market_data_body
    assert "상승/하락 종목 비율" in market_data_body
    assert "KOSPI 장중 상승 종목 비율" in market_data_body
    assert "미국/글로벌 야간 흐름" in market_data_body
    assert "한국 관련 야간 프록시(EWY)" in market_data_body
    assert "S&amp;P500 선물" in market_data_body
    assert "preview score" in market_data_body
    assert "시장 브리핑" in home_body
    assert "퀀트투자 모델 해석에 필요한 시장 상태를 같은 기준으로 정리합니다." in home_body
    assert "다양한 시장 데이터 기반의 상황별 퀀트투자 모델 정보 서비스" in home_body
    assert "퀀트투자 모델" in home_body
    assert "market-state-bar" in home_body
    assert "퀀트모델 시장 흐름" in home_body
    assert "오늘 장중 흐름" in home_body
    assert "혼조 출발 가능성" in home_body
    assert "국내 야간선물" in home_body
    assert "+0.42%" in home_body
    assert "최근 추세와 시장 내부 신호를 반영한 퀀트모델 기준 흐름입니다." in home_body
    assert "상승 유지, 단기 조정 동반" in home_body
    assert MARKET_REFERENCE_NOTE in today_body
    assert "브리핑 톤" in today_body
    assert "내일 시장 전망" in today_body
    assert "국내 야간선물 +0.42%" in today_body
    assert "이번 해석 배경" in today_body
    assert "20일선 위 종목 비율과 변동성 지표를 함께 볼 필요가 있습니다." in today_body
    assert "market-state-bar" in today_body
    assert (
        "퀀트모델 시장 흐름은 상승이지만, 오늘 장중에는 단기 조정 흐름이 나타납니다." in today_body
    )
    assert "당일 지수와 breadth를 반영한 장중 흐름 참고값입니다." in today_body
    assert "강한 약세" in today_body
    assert "서비스 상태" in changes_body
    assert "상태 타임라인" not in market_body
    assert "상태 전이 요약" not in market_body
    assert "ai_logos/gemini.svg" in market_body
    assert "ai_logos/gemini.svg" in market_body
    assert "추세는 살아 있지만 속도는 과열 구간이 아닙니다." in market_body
    assert "안정형 모델" in changes_body
    assert "주간 모델 조정" in changes_body
    assert "안정형 모델" in changes_body
    assert "주간 모델 조정" in changes_body
    assert "퀀트모델 시장 흐름" in market_body
    assert "오늘 장중 흐름" in market_body
    assert "내일 시장 전망" in market_body
    assert "야간 핵심 자산" in market_body
    assert "국내 야간선물" in market_body
    assert "S&amp;P500 선물" in market_body
    assert "원달러" in market_body
    assert "해외 야간 흐름과 단기 변동성을 감안하면 혼조 출발 가능성이 있습니다." in market_body
    assert "강한 약세" in market_body
    assert "상승 유지, 단기 조정 동반" in market_body
    assert (
        "장중 흐름 근거: 단기 변동성과 하락 종목 비중이 커지며 참고용 약세 압력이 " "나타났습니다."
    ) in market_body
    assert "이전상태 대비" not in market_body
    assert "모델 해석" in market_body
    assert "긍정적 요인" in market_body
    assert "수급 개선 신호가 일부 업종에서 확인됩니다." in market_body
    assert "뉴스 이벤트에 따른 업종별 차별화 가능성이 있습니다." in market_body
    assert "긍정: 수급 개선" not in market_body
    assert "리스크: 뉴스 이벤트" not in market_body
    assert summary_response.status_code == 200
    assert summary_response.get_json()["data"]["state_label"] == "중립"
    assert detail_response.status_code == 200
    assert detail_response.get_json()["data"]["positive_points"][0] == "60일선 위 종목 비율 양호"
    assert timeline_response.status_code == 200
    assert timeline_response.get_json()["data"]["title"] == "상태 타임라인"
    assert asset_strength_response.status_code == 200
    assert asset_strength_response.get_json()["data"]["top_assets"][0]["asset_group"] == "KOSPI"
    assert timeline_history_response.status_code == 200
    assert (
        timeline_history_response.get_json()["data"]["schema_version"]
        == "market_timeline_history.v1"
    )
    assert asset_strength_history_response.status_code == 200
    assert (
        asset_strength_history_response.get_json()["data"]["schema_version"]
        == "market_asset_strength_history.v1"
    )
    assert state_transition_response.status_code == 200
    assert state_transition_response.get_json()["data"]["current"]["duration_hours"] == 31.1
    assert model_background_response.status_code == 200
    assert model_background_response.get_json()["data"]["briefing_tone"] == "중립 해석 환경"
    assert next_day_preview_response.status_code == 200
    assert next_day_preview_response.get_json()["data"]["preview_label"] == "혼조 출발 가능성"
    assert tabs_response.status_code == 200
    assert tabs_response.get_json()["data"]["tabs"][0]["label"] == "시장 상태"
    assert live_context_response.status_code == 200
    assert live_context_response.get_json()["data"]["cards"][0]["title"] == "오늘 장중 흐름"
    assert data_guide_response.status_code == 200
    assert data_guide_response.get_json()["data"]["sections"][0]["title"] == "official"
    assert dart_summary_response.status_code == 200
    assert dart_summary_response.get_json()["data"]["filing_count_total"] == 128
    assert dart_summary_history_response.status_code == 200
    assert dart_summary_history_response.get_json()["data"]["series"][-1]["risk_event_count"] == 7
    assert breadth_detail_response.status_code == 200
    assert (
        breadth_detail_response.get_json()["data"]["summary"]["latest_close_asof"] == "2026-04-29"
    )
    assert breadth_detail_history_response.status_code == 200
    assert (
        breadth_detail_history_response.get_json()["data"]["close_series"][-1]["above_20dma_ratio"]
        == 0.48
    )
    assert us_macro_panel_response.status_code == 200
    assert (
        us_macro_panel_response.get_json()["data"]["headline_line"]
        == "야간 글로벌 지표는 혼조권에서 움직였습니다."
    )
    assert us_macro_panel_history_response.status_code == 200
    assert environment_api_response.status_code == 200
    assert environment_api_response.get_json()["data"]["sections"][0]["section_key"] == (
        "domestic_source"
    )
    assert (
        us_macro_panel_history_response.get_json()["data"]["preview_series"][-1]["preview_score"]
        == 0.24
    )
    assert manifest_response.status_code == 200
    assert manifest_response.get_json()["consumer"] == "QuantService"


def test_market_composite_chart_date_labels_keep_latest_without_overlap() -> None:
    base_date = datetime(2026, 1, 1)
    dates = [(base_date + timedelta(days=index)).date().isoformat() for index in range(130)]
    chart = {
        "score_range": {"min": -3, "max": 3},
        "series": [
            {
                "series_id": "short_term_market_condition",
                "label": "단기",
                "points": [
                    {"date": date_text, "value": (index % 7) - 3}
                    for index, date_text in enumerate(dates)
                ],
            }
        ],
    }

    view = _build_market_composite_chart_view(chart)
    labels = view["date_labels"]
    gaps = [right["x"] - left["x"] for left, right in zip(labels, labels[1:])]

    assert labels[-1]["label"] == dates[-1][5:]
    assert all(gap >= 88 for gap in gaps)


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


def test_market_analysis_remote_reads_api_history_from_history_base(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    history_dir = settings.market_analysis_dir.parent / "history"
    history_dir.mkdir(parents=True)

    filename = "api_v1_market_analysis_timeline_history.json"
    current_path = settings.market_analysis_dir / filename
    history_path = history_dir / filename
    original_payload = json.loads(current_path.read_text(encoding="utf-8-sig"))
    history_path.write_text(
        json.dumps(original_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    stale_payload = dict(original_payload)
    stale_payload["asof"] = "2026-03-20T12:00:00+09:00"
    current_path.write_text(
        json.dumps(stale_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    remote_settings = replace(
        settings,
        market_analysis_source="remote",
        market_analysis_base_url=settings.market_analysis_dir.as_uri(),
    )
    api = MarketAnalysisMockApi(remote_settings)

    bundle = api.load_bundle(force_refresh=True)

    assert bundle.source_name == "market-analysis-remote"
    assert bundle.api_timeline_history["asof"] == original_payload["asof"]
    assert not bundle.warnings


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
                "theme_label": "모델 해석 참고",
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
    assert "퀀트투자 모델 브리핑" in body
    assert "모델 해석" in body
    assert "한 줄 요약 1" in body
    assert "Gemini 가 읽어주는 시장분위기" not in body


def test_market_analysis_ai_briefs_support_gemini_four_by_four_payload(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(
        settings.market_analysis_dir,
        ai_providers=[
            {
                "provider": "gemini",
                "label": "Gemini",
                "theme_label": "시장 분위기 참고",
                "enabled": True,
                "generated_at": "2026-05-11T10:06:00+09:00",
                "source": "gemini:gemini-2.5-flash",
                "summary_lines": [
                    "긍정: 지수 반등이 이어지고 있습니다.",
                    "긍정: 환율 부담이 완화되었습니다.",
                    "긍정: 수급 개선이 일부 업종에서 보입니다.",
                    "긍정: 선물 흐름이 장초반을 지지합니다.",
                    "리스크: 종목 확산은 아직 제한적입니다.",
                    "리스크: 뉴스 이벤트가 변동성을 키울 수 있습니다.",
                    "리스크: 단기 차익실현 가능성이 남아 있습니다.",
                    "리스크: 대외 금리 변화는 계속 확인이 필요합니다.",
                ],
            }
        ],
    )
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/market-analysis")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "긍정적 요인" in body
    assert "리스크 요인" in body
    assert "선물 흐름이 장초반을 지지합니다." in body
    assert "대외 금리 변화는 계속 확인이 필요합니다." in body
    assert "긍정: 선물 흐름" not in body
    assert "리스크: 대외 금리" not in body


def test_market_analysis_optional_sections_hide_gracefully_when_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    for filename in (
        "quantservice_market_timeline.json",
        "quantservice_market_asset_strength.json",
        "quantservice_market_state_transition.json",
        "quantservice_market_model_background.json",
        "api_v1_market_analysis_timeline.json",
        "api_v1_market_analysis_asset_strength.json",
        "api_v1_market_analysis_state_transition.json",
        "api_v1_market_analysis_model_background.json",
        "quantservice_market_next_day_preview.json",
        "market_next_day_preview_manifest.json",
        "api_v1_market_analysis_next_day_preview.json",
    ):
        target = settings.market_analysis_dir / filename
        if target.exists():
            target.unlink()
    app = create_app(settings)
    client = app.test_client()

    home_response = client.get("/")
    today_response = client.get("/today")
    market_response = client.get("/market-analysis")

    assert home_response.status_code == 200
    assert today_response.status_code == 200
    assert market_response.status_code == 200
    assert "현재 상대적으로 강한 자산" not in home_response.get_data(as_text=True)
    assert "내일 시장 전망 참고" not in home_response.get_data(as_text=True)
    assert "이번 해석 배경" not in today_response.get_data(as_text=True)
    assert "내일 시장 전망 참고" not in today_response.get_data(as_text=True)
    assert "상태 타임라인" not in market_response.get_data(as_text=True)
    assert "자산군 상대강도" not in market_response.get_data(as_text=True)
    assert "내일 시장 전망 참고" not in market_response.get_data(as_text=True)


def test_market_state_bridge_keeps_dual_bar_with_reference_fallback_when_disabled(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    for filename, root_path in (
        ("quantservice_market_home.json", ["hero"]),
        ("quantservice_market_today.json", ["market_bridge"]),
        ("quantservice_market_page.json", []),
    ):
        target = settings.market_analysis_dir / filename
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        container = payload
        for key in root_path:
            container = container[key]
        container["state_intraday_bridge"] = {"enabled": False}
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    next_day_target = settings.market_analysis_dir / "quantservice_market_next_day_preview.json"
    next_day_payload = json.loads(next_day_target.read_text(encoding="utf-8-sig"))
    next_day_payload["active_now"] = False
    next_day_target.write_text(
        json.dumps(next_day_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    api_next_day_target = (
        settings.market_analysis_dir / "api_v1_market_analysis_next_day_preview.json"
    )
    api_next_day_payload = json.loads(api_next_day_target.read_text(encoding="utf-8-sig"))
    api_next_day_payload["data"]["active_now"] = False
    api_next_day_target.write_text(
        json.dumps(api_next_day_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    app = create_app(settings)
    client = app.test_client()

    home_body = client.get("/").get_data(as_text=True)
    today_body = client.get("/today").get_data(as_text=True)
    market_body = client.get("/market-analysis").get_data(as_text=True)

    assert "퀀트모델 시장 흐름" in home_body
    assert "오늘 장중 흐름" in today_body
    assert "전일 기준 참고" in market_body


def test_market_next_day_preview_shows_valid_korean_night_signals(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    app = create_app(settings)
    client = app.test_client()

    market_body = client.get("/market-analysis").get_data(as_text=True)

    assert "국내 야간선물" in market_body
    assert "미국 상장 한국 ETF" in market_body


def test_market_next_day_preview_falls_back_to_ewy_when_kospi_night_fut_missing(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    for filename in (
        "quantservice_market_next_day_preview.json",
        "api_v1_market_analysis_next_day_preview.json",
    ):
        target = settings.market_analysis_dir / filename
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        container = payload.get("data") if filename.startswith("api_") else payload
        container["overnight_assets"] = [
            asset
            for asset in (container.get("overnight_assets") or [])
            if asset.get("asset_code") != "KOSPI200_NIGHT_FUT"
        ]
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    app = create_app(settings)
    client = app.test_client()

    home_body = client.get("/").get_data(as_text=True)
    market_body = client.get("/market-analysis").get_data(as_text=True)

    assert "국내 야간선물" not in home_body
    assert "미국 상장 한국 ETF" in home_body
    assert "+0.33%" in home_body
    assert "국내 야간선물" not in market_body
    assert "미국 상장 한국 ETF" in market_body


def test_market_next_day_preview_hides_fallback_kospi_night_fut(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    for filename in (
        "quantservice_market_next_day_preview.json",
        "api_v1_market_analysis_next_day_preview.json",
    ):
        target = settings.market_analysis_dir / filename
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        container = payload.get("data") if filename.startswith("api_") else payload
        for asset in container.get("overnight_assets") or []:
            if asset.get("asset_code") == "KOSPI200_NIGHT_FUT":
                asset["change_pct"] = None
                asset["is_fallback"] = True
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    app = create_app(settings)
    client = app.test_client()

    market_body = client.get("/market-analysis").get_data(as_text=True)

    assert "국내 야간선물" not in market_body
    assert "미국 상장 한국 ETF" in market_body


def test_market_next_day_preview_hides_gracefully_when_inactive(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    target = settings.market_analysis_dir / "quantservice_market_next_day_preview.json"
    api_target = settings.market_analysis_dir / "api_v1_market_analysis_next_day_preview.json"
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    payload["active_now"] = False
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    api_payload = json.loads(api_target.read_text(encoding="utf-8-sig"))
    api_payload["data"]["active_now"] = False
    api_target.write_text(
        json.dumps(api_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    app = create_app(settings)
    client = app.test_client()

    home_body = client.get("/").get_data(as_text=True)
    today_body = client.get("/today").get_data(as_text=True)
    market_body = client.get("/market-analysis").get_data(as_text=True)
    api_response = client.get("/api/v1/market-analysis/next-day-preview")

    assert "내일 시장 전망 참고" not in home_body
    assert "내일 시장 전망 참고" not in today_body
    assert "내일 시장 전망 참고" not in market_body
    assert "내일 시장 전망" in market_body
    assert "market-next-day-card--muted" in market_body
    assert api_response.status_code == 200
    assert api_response.get_json()["data"]["active_now"] is False


def seed_trading_sign_snapshot(
    target_dir: Path,
    *,
    generated_at: str = "2026-04-02T13:21:50",
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    state_order = ["매수", "보유", "주의", "매도", "매수 대기"]
    model_specs = [
        ("STABLE", "안정형"),
        ("BALANCED", "균형형"),
        ("GROWTH", "성장형"),
        ("AUTO", "자동전환형"),
    ]
    models = []
    for model_code, model_name in model_specs:
        models.append(
            {
                "model_code": model_code,
                "model_name": model_name,
                "signal_date": "2026-04-02",
                "record_count": 3,
                "state_counts": {
                    "매수": 1,
                    "보유": 1,
                    "주의": 1,
                    "매도": 0,
                    "매수 대기": 0,
                },
                "ui_block": {
                    "title": "매매 신호(전일 종가 기준)",
                    "description": (
                        "이 신호는 전일 종가 기준으로 계산된 참고용 일간 점검 정보입니다."
                    ),
                    "disclaimer": (
                        "이 상태는 공개 규칙 기반 모델의 참고용 해석이며 특정 이용자에 대한 "
                        "개별 매매 지시가 아닙니다."
                    ),
                    "signal_date": "2026-04-02",
                    "data_asof_date": "2026-04-01",
                    "generated_at": generated_at,
                    "profile_code": model_code,
                    "state_chips": [
                        {
                            "state": state,
                            "count": {
                                "매수": 1,
                                "보유": 1,
                                "주의": 1,
                                "매도": 0,
                                "매수 대기": 0,
                            }[state],
                        }
                        for state in state_order
                    ],
                    "sections": [
                        {
                            "section_key": "recommended",
                            "title": "추천 종목 신호",
                            "record_count": 1,
                            "state_counts": {
                                "매수": 1,
                                "보유": 0,
                                "주의": 0,
                                "매도": 0,
                                "매수 대기": 0,
                            },
                            "signals": [
                                {
                                    "ticker": "005930",
                                    "security_name": "삼성전자",
                                    "current_state": "매수",
                                    "reason_summary": (
                                        "전일 종가 기준으로 신규 진입 조건을 충족했습니다."
                                    ),
                                    "latest_state_change_date": "2026-04-02",
                                    "entry_score": 0.71,
                                    "exit_risk_score": 0.1,
                                }
                            ],
                        },
                        {
                            "section_key": "held",
                            "title": "보유 종목 신호",
                            "record_count": 2,
                            "state_counts": {
                                "매수": 0,
                                "보유": 1,
                                "주의": 1,
                                "매도": 0,
                                "매수 대기": 0,
                            },
                            "signals": [
                                {
                                    "ticker": "000660",
                                    "security_name": "SK하이닉스",
                                    "current_state": "보유",
                                    "reason_summary": (
                                        "중장기 추세가 유지돼 보유 기준을 충족하고 있습니다."
                                    ),
                                    "latest_state_change_date": "2026-04-02",
                                    "entry_score": 0.45,
                                    "exit_risk_score": 0.0,
                                },
                                {
                                    "ticker": "035420",
                                    "security_name": "NAVER",
                                    "current_state": "주의",
                                    "reason_summary": (
                                        "보유 종목은 추가 확인이 필요한 경고 상태입니다."
                                    ),
                                    "latest_state_change_date": "2026-04-02",
                                    "entry_score": 0.39,
                                    "exit_risk_score": 0.25,
                                },
                            ],
                        },
                    ],
                },
            }
        )

    overview = {
        "asof": "2026-04-02",
        "generated_at": generated_at,
        "schema_version": "v1",
        "summary": {
            "model_count": 4,
            "signal_count": 12,
            "state_counts": {"매수": 4, "보유": 4, "주의": 4, "매도": 0, "매수 대기": 0},
            "state_order": state_order,
        },
        "models": [
            {
                "model_code": model["model_code"],
                "model_name": model["model_name"],
                "signal_date": model["signal_date"],
                "record_count": model["record_count"],
                "state_counts": model["state_counts"],
            }
            for model in models
        ],
    }
    detail = {
        "asof": "2026-04-02",
        "generated_at": generated_at,
        "schema_version": "v1",
        "models": models,
    }
    manifest = {
        "asof": "2026-04-02",
        "generated_at": generated_at,
        "schema_version": "v1",
        "files": [
            "tradingsign_overview.json",
            "tradingsign_model_detail.json",
            "tradingsign_manifest.json",
        ],
        "freshness": {
            "signal_refresh_frequency": "daily_eod",
            "data_cutoff": "previous_trading_day_close",
        },
    }
    for filename, payload in (
        ("tradingsign_overview.json", overview),
        ("tradingsign_model_detail.json", detail),
        ("tradingsign_manifest.json", manifest),
    ):
        target_dir.joinpath(filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8-sig",
        )


def test_today_page_renders_trading_sign_block_per_model(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    seed_trading_sign_snapshot(settings.public_data_dir / "trading_sign" / "current")

    app = create_app(settings)
    client = app.test_client()

    body = client.get("/today").get_data(as_text=True)

    assert "매매 신호(전일 종가 기준)" in body
    assert "추천 종목 신호" in body or "일간 신호 데이터가 아직 준비되지 않았습니다." in body
    assert "삼성전자" in body


def test_trading_sign_remote_current_precedes_local_snapshot(tmp_path: Path) -> None:
    settings = replace(
        build_settings(tmp_path),
        snapshot_source="remote",
        snapshot_gcs_base_url=(tmp_path / "remote_root").as_uri(),
    )
    seed_trading_sign_snapshot(
        settings.public_data_dir / "trading_sign" / "current", generated_at="2026-04-01T00:00:00"
    )
    remote_dir = tmp_path / "remote_root" / "trading_sign" / "current"
    seed_trading_sign_snapshot(remote_dir, generated_at="2026-04-06T15:33:43")

    api = TradingSignSnapshotApi(settings)
    bundle = api.load_bundle(force_refresh=True)

    assert bundle.source_name.startswith("remote:")
    assert bundle.generated_at == "2026-04-06T15:33:43"
    assert bundle.warnings == []


def test_trading_sign_remote_current_works_with_detail_only_during_publish_window(
    tmp_path: Path,
) -> None:
    settings = replace(
        build_settings(tmp_path),
        snapshot_source="remote",
        snapshot_gcs_base_url=(tmp_path / "remote_root").as_uri(),
    )
    remote_dir = tmp_path / "remote_root" / "trading_sign" / "current"
    seed_trading_sign_snapshot(remote_dir, generated_at="2026-04-06T15:33:43")
    (remote_dir / "tradingsign_overview.json").unlink()
    (remote_dir / "tradingsign_manifest.json").unlink()

    api = TradingSignSnapshotApi(settings)
    bundle = api.load_bundle(force_refresh=True)
    status = api.get_status(force_refresh=True)

    assert bundle.source_name.startswith("remote:")
    assert bundle.detail.get("models")
    assert status.state in {"healthy", "stale"}
    assert status.snapshot_accessible is True
    assert any("detail 기준" in warning for warning in bundle.warnings)


def test_today_page_shows_trading_sign_fallback_when_snapshot_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)

    app = create_app(settings)
    client = app.test_client()

    body = client.get("/today").get_data(as_text=True)

    assert "이번 주 모델 포트폴리오" in body
    assert "일간 신호 데이터가 아직 준비되지 않았습니다. 다음 갱신 후 다시 확인해 주세요." in body


def test_today_page_keeps_trading_sign_block_when_snapshot_is_stale(tmp_path: Path) -> None:
    settings = replace(build_settings(tmp_path), snapshot_stale_after_hours=1)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    seed_trading_sign_snapshot(
        settings.public_data_dir / "trading_sign" / "current",
        generated_at="2026-04-10T00:00:00",
    )

    app = create_app(settings)
    client = app.test_client()

    body = client.get("/today").get_data(as_text=True)

    assert "매매 신호(전일 종가 기준)" in body
    assert "일간 신호 데이터 업데이트가 지연되어 최근 기준 스냅샷을 표시합니다." in body
    assert "삼성전자" in body


def test_today_page_renders_allocation_rank_and_strategy_fit(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    app = create_app(settings)
    client = app.test_client()

    body = client.get("/today").get_data(as_text=True)

    assert "순위" in body
    assert "전략 적합도" in body
    assert "target_weight_proxy" in body


def test_market_state_bridge_shows_public_fallback_label_when_intraday_label_missing(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    for filename, root_path in (
        ("quantservice_market_home.json", ["hero"]),
        ("quantservice_market_today.json", ["market_bridge"]),
        ("quantservice_market_page.json", []),
    ):
        target = settings.market_analysis_dir / filename
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        container = payload
        for key in root_path:
            container = container[key]
        bridge = container.get("state_intraday_bridge") or {}
        bridge.pop("intraday_state_label", None)
        bridge["enabled"] = True
        container["state_intraday_bridge"] = bridge
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    app = create_app(settings)
    client = app.test_client()

    home_body = client.get("/").get_data(as_text=True)
    today_body = client.get("/today").get_data(as_text=True)
    market_body = client.get("/market-analysis").get_data(as_text=True)

    assert "전일 기준 참고" in home_body
    assert "전일 기준 참고" in today_body
    assert "전일 기준 참고" in market_body


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
                "theme_label": "모델 해석 참고",
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
    assert "퀀트투자 모델 브리핑" in body
    assert "퀀트투자 모델 브리핑 준비 중" in body


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


def test_signup_rejects_missing_csrf_token_and_feedback_page_is_removed(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    signup_response = client.post(
        "/signup",
        data={"action": "request_code", "phone_number": "01011112222", "next": "/today"},
    )
    feedback_response = client.post("/feedback")

    assert signup_response.status_code == 400
    assert feedback_response.status_code == 404


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


def seed_analytics_preview_bundle(bundle_dir: Path, *, web_publish_enabled: bool = False) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "asof": "2026-03-25",
        "internal_preview_only": True,
        "web_publish_enabled": web_publish_enabled,
        "bundle": "p1",
        "pages": ["today_model_info", "model_changes", "model_compare"],
        "files": {
            "today_model_info": str(bundle_dir / "today_model_info_20260325.json"),
            "model_changes": str(bundle_dir / "model_changes_20260325.json"),
            "model_compare": str(bundle_dir / "model_compare_20260325.json"),
        },
    }
    today_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "risk_grade": "high",
                "run_id": "RUN-S3",
                "backtest_period": {"start_date": "2019-01-01", "end_date": "2026-03-25"},
                "headline_metrics": {
                    "cagr": 0.31,
                    "mdd": -0.14,
                    "sharpe": 1.72,
                    "current_drawdown": -0.02,
                    "return_4w": 0.08,
                    "return_12w": 0.19,
                },
                "asset_mix": {
                    "stock_weight": 1.0,
                    "etf_weight": 0.0,
                    "cash_weight": 0.0,
                },
                "recent_change_summary": {
                    "new_8w": 7,
                    "exit_8w": 5,
                    "increase_8w": 0,
                    "decrease_8w": 0,
                },
                "top_holdings": [
                    {
                        "ticker": "005930",
                        "name": "삼성전자",
                        "asset_type": "STOCK",
                        "weight": 0.05,
                    },
                    {
                        "ticker": "000660",
                        "name": "SK하이닉스",
                        "asset_type": "STOCK",
                        "weight": 0.05,
                    },
                ],
                "holding_highlights": [
                    {
                        "ticker": "005930",
                        "name": "삼성전자",
                        "asset_type": "STOCK",
                        "holding_days_observed": 63,
                        "latest_weight": 0.05,
                        "latest_return_since_entry": None,
                    }
                ],
            }
        ],
    }
    changes_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "summary": {"new_8w": 7, "exit_8w": 5, "increase_8w": 0, "decrease_8w": 0},
                "items": [
                    {
                        "week_end": "2026-03-20",
                        "ticker": "005930",
                        "name": "삼성전자",
                        "asset_type": "STOCK",
                        "change_type": "new",
                        "weight_prev": 0.0,
                        "weight_curr": 0.05,
                        "delta_weight": 0.05,
                    }
                ],
            }
        ],
    }
    compare_payload = {
        "meta": dict(manifest),
        "rows": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "risk_grade": "high",
                "cagr": 0.31,
                "mdd": -0.14,
                "sharpe": 1.72,
                "return_4w": 0.08,
                "return_12w": 0.19,
                "current_drawdown": -0.02,
                "relative_strength_vs_benchmark_4w": 0.01,
                "stock_weight": 1.0,
                "etf_weight": 0.0,
                "cash_weight": 0.0,
                "new_8w": 7,
                "exit_8w": 5,
                "increase_8w": 0,
                "decrease_8w": 0,
            }
        ],
    }
    (bundle_dir / "bundle_manifest_20260325.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "today_model_info_20260325.json").write_text(
        json.dumps(today_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "model_changes_20260325.json").write_text(
        json.dumps(changes_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "model_compare_20260325.json").write_text(
        json.dumps(compare_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_analytics_preview_p2_bundle(
    bundle_dir: Path, *, web_publish_enabled: bool = False
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "asof": "2026-03-25",
        "internal_preview_only": True,
        "web_publish_enabled": web_publish_enabled,
        "bundle": "p2",
        "pages": ["portfolio_structure", "holding_lifecycle"],
        "files": {
            "portfolio_structure": str(bundle_dir / "portfolio_structure_20260325.json"),
            "holding_lifecycle": str(bundle_dir / "holding_lifecycle_20260325.json"),
        },
    }
    portfolio_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "risk_grade": "high",
                "latest_asset_mix": {
                    "stock_weight": 0.82,
                    "etf_weight": 0.12,
                    "cash_weight": 0.06,
                    "other_weight": 0.0,
                },
                "asset_mix_trend_26w": [
                    {
                        "week_end": "2026-02-27",
                        "stock_weight": 0.78,
                        "etf_weight": 0.15,
                        "cash_weight": 0.07,
                        "other_weight": 0.0,
                    },
                    {
                        "week_end": "2026-03-06",
                        "stock_weight": 0.80,
                        "etf_weight": 0.14,
                        "cash_weight": 0.06,
                        "other_weight": 0.0,
                    },
                    {
                        "week_end": "2026-03-13",
                        "stock_weight": 0.81,
                        "etf_weight": 0.13,
                        "cash_weight": 0.06,
                        "other_weight": 0.0,
                    },
                    {
                        "week_end": "2026-03-20",
                        "stock_weight": 0.82,
                        "etf_weight": 0.12,
                        "cash_weight": 0.06,
                        "other_weight": 0.0,
                    },
                ],
                "current_allocation_breakdown": [
                    {
                        "ticker": "095340",
                        "name": "ISC",
                        "asset_type": "STOCK",
                        "weight": 0.05,
                        "rank_no": 1,
                    },
                    {
                        "ticker": "069500",
                        "name": "KODEX 200",
                        "asset_type": "ETF",
                        "weight": 0.12,
                        "rank_no": 2,
                    },
                ],
                "concentration": {
                    "top1_weight": 0.05,
                    "top3_weight": 0.15,
                    "top5_weight": 0.25,
                    "current_holdings_count": 20,
                },
                "quality_context": {
                    "return_4w": 0.08,
                    "return_12w": 0.19,
                    "cash_weight_avg_4w": 0.07,
                    "holdings_count_avg_4w": 20,
                },
                "date_context": {
                    "asof_date": "2026-03-25",
                    "signal_date": "2026-03-21",
                    "asset_mix_week_end": "2026-03-20",
                },
            }
        ],
    }
    lifecycle_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "current_holdings_lifecycle": [
                    {
                        "ticker": "095340",
                        "name": "ISC",
                        "asset_type": "STOCK",
                        "first_seen_date": "2026-01-15",
                        "last_seen_date": "2026-03-20",
                        "holding_days_observed": 28,
                        "latest_weight": 0.05,
                        "latest_return_since_entry": None,
                    }
                ],
                "longest_historical_holdings": [
                    {
                        "ticker": "095340",
                        "name": "ISC",
                        "asset_type": "STOCK",
                        "holding_days_observed": 28,
                        "first_seen_date": "2026-01-15",
                        "last_seen_date": "2026-03-20",
                        "latest_weight": 0.05,
                    }
                ],
                "recent_new_entries_8w": [
                    {
                        "week_end": "2026-03-20",
                        "ticker": "095340",
                        "name": "ISC",
                        "delta_weight": 0.05,
                    }
                ],
                "recent_exits_8w": [],
                "current_holding_highlights": [
                    {
                        "ticker": "095340",
                        "name": "ISC",
                        "asset_type": "STOCK",
                        "holding_days_observed": 28,
                        "latest_weight": 0.05,
                        "latest_return_since_entry": None,
                    }
                ],
                "date_context": {
                    "asof_date": "2026-03-25",
                    "signal_date": "2026-03-21",
                    "effective_date": "2026-03-24",
                },
            }
        ],
    }
    (bundle_dir / "bundle_manifest_20260325.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "portfolio_structure_20260325.json").write_text(
        json.dumps(portfolio_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "holding_lifecycle_20260325.json").write_text(
        json.dumps(lifecycle_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_analytics_preview_p3_bundle(
    bundle_dir: Path, *, web_publish_enabled: bool = False
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "asof": "2026-03-25",
        "internal_preview_only": True,
        "web_publish_enabled": web_publish_enabled,
        "bundle": "p3",
        "pages": ["model_quality", "weekly_briefing"],
        "files": {
            "model_quality": str(bundle_dir / "model_quality_20260325.json"),
            "weekly_briefing": str(bundle_dir / "weekly_briefing_20260325.json"),
        },
    }
    model_quality_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "latest_quality": {
                    "cagr": 0.31,
                    "mdd": -0.14,
                    "sharpe": 1.72,
                    "return_4w": 0.08,
                    "return_12w": 0.19,
                    "current_drawdown": -0.02,
                    "relative_strength_vs_benchmark_4w": 0.01,
                    "relative_strength_vs_benchmark_12w": 0.03,
                    "relative_strength_vs_benchmark_52w": 0.09,
                    "cash_weight_avg_4w": 0.05,
                    "holdings_count_avg_4w": 20,
                    "turnover_1w": 0.04,
                    "turnover_avg_4w": 0.06,
                    "top1_weight": 0.11,
                    "top3_weight": 0.27,
                    "top5_weight": 0.39,
                    "holdings_hhi": 0.087,
                },
                "quality_trend_26w": [
                    {
                        "week_end": "2026-03-06",
                        "return_4w": 0.05,
                        "return_12w": 0.14,
                        "drawdown_current": -0.03,
                    },
                    {
                        "week_end": "2026-03-13",
                        "return_4w": 0.07,
                        "return_12w": 0.17,
                        "drawdown_current": -0.02,
                    },
                    {
                        "week_end": "2026-03-20",
                        "return_4w": 0.08,
                        "return_12w": 0.19,
                        "drawdown_current": -0.02,
                    },
                ],
                "change_density": {
                    "new_8w": 7,
                    "exit_8w": 5,
                    "increase_8w": 0,
                    "decrease_8w": 0,
                },
                "date_context": {
                    "asof_date": "2026-03-25",
                    "quality_week_end": "2026-03-20",
                },
                "quality_checks": [
                    {
                        "check_name": "asset_mix_gross_weight",
                        "status": "ok",
                        "metric_value": 1.0,
                        "detail": "합계 100%",
                    },
                    {
                        "check_name": "lifecycle_reentries",
                        "status": "review",
                        "metric_value": 2,
                        "detail": "45일 분리 규칙 확인",
                    },
                ],
                "performance_interpretation": {
                    "window_weeks": 12,
                    "window_start_week_end": "2025-12-27",
                    "window_end_week_end": "2026-03-20",
                    "cumulative_return_12w": 0.19,
                    "best_weekly_return_12w": 0.06,
                    "best_weekly_return_week_end": "2026-02-21",
                    "worst_weekly_return_12w": -0.04,
                    "worst_weekly_return_week_end": "2026-01-31",
                    "positive_weeks_12w": 8,
                    "negative_weeks_12w": 3,
                    "flat_weeks_12w": 1,
                    "annualized_volatility_12w": 0.22,
                    "top_contributors_12w": [
                        {
                            "ticker": "005930",
                            "name": "삼성전자",
                            "estimated_contribution_12w": 0.04,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "estimated_contribution_12w": 0.03,
                        },
                    ],
                },
            }
        ],
    }
    weekly_briefing_payload = {
        "meta": dict(manifest),
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "summary": {
                    "return_4w": 0.08,
                    "return_12w": 0.19,
                    "current_drawdown": -0.02,
                    "cash_weight": 0.05,
                    "new_8w": 7,
                    "exit_8w": 5,
                    "relative_strength_vs_benchmark_12w": 0.03,
                    "turnover_avg_4w": 0.06,
                    "top5_weight": 0.39,
                },
                "briefing_points": [
                    "최근 4주 성과가 양호합니다.",
                    "최근 12주 흐름은 우상향입니다.",
                    "최근 8주 변화 밀도가 높습니다.",
                ],
                "top_holdings": [
                    {
                        "ticker": "005930",
                        "name": "삼성전자",
                        "asset_type": "STOCK",
                        "weight": 0.05,
                        "rank_no": 1,
                    }
                ],
                "one_week_changes": [
                    {
                        "week_end": "2026-03-20",
                        "ticker": "005930",
                        "name": "삼성전자",
                        "change_type": "new",
                        "delta_weight": 0.05,
                    }
                ],
                "recent_changes_8w": [
                    {
                        "week_end": "2026-03-20",
                        "ticker": "005930",
                        "name": "삼성전자",
                        "change_type": "new",
                        "delta_weight": 0.05,
                    }
                ],
                "date_context": {
                    "asof_date": "2026-03-25",
                    "week_end": "2026-03-20",
                },
                "performance_interpretation": {
                    "window_weeks": 12,
                    "window_start_week_end": "2025-12-27",
                    "window_end_week_end": "2026-03-20",
                    "cumulative_return_12w": 0.19,
                    "best_weekly_return_12w": 0.06,
                    "best_weekly_return_week_end": "2026-02-21",
                    "worst_weekly_return_12w": -0.04,
                    "worst_weekly_return_week_end": "2026-01-31",
                    "positive_weeks_12w": 8,
                    "negative_weeks_12w": 3,
                    "flat_weeks_12w": 1,
                    "annualized_volatility_12w": 0.22,
                    "top_contributors_12w": [
                        {
                            "ticker": "005930",
                            "name": "삼성전자",
                            "estimated_contribution_12w": 0.04,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "estimated_contribution_12w": 0.03,
                        },
                    ],
                },
            }
        ],
    }
    (bundle_dir / "bundle_manifest_20260325.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "model_quality_20260325.json").write_text(
        json.dumps(model_quality_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "weekly_briefing_20260325.json").write_text(
        json.dumps(weekly_briefing_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_internal_preview_pages_require_admin_and_render_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview"
    seed_analytics_preview_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/analytics-p1/today-model-info").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p1/today-model-info",
        follow_redirects=True,
    )

    today_response = client.get("/admin/analytics-p1/today-model-info")
    changes_response = client.get("/admin/analytics-p1/model-changes")
    compare_response = client.get("/admin/analytics-p1/model-compare")

    assert today_response.status_code == 200
    today_body = today_response.get_data(as_text=True)
    assert "오늘의 모델 정보" in today_body
    assert "Quant S3" in today_body
    assert "상위 보유종목" in today_body
    assert changes_response.status_code == 200
    assert "모델 변화" in changes_response.get_data(as_text=True)
    assert compare_response.status_code == 200
    assert "모델 비교" in compare_response.get_data(as_text=True)


def test_internal_preview_routes_are_hidden_in_production_without_allowed_admin(
    tmp_path: Path, monkeypatch
) -> None:
    settings = replace(
        build_settings(tmp_path, internal_preview_enabled=True),
        app_env="production",
    )
    preview_dir = tmp_path / "analytics_preview"
    seed_analytics_preview_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p1/today-model-info",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p1/today-model-info")

    assert response.status_code == 404


def test_internal_preview_routes_allow_named_admin_in_production(
    tmp_path: Path, monkeypatch
) -> None:
    admin_email = "admin@example.com"
    settings = replace(
        build_settings(tmp_path, internal_preview_enabled=True),
        app_env="production",
        analytics_preview_allowed_emails=(admin_email,),
    )
    preview_dir = tmp_path / "analytics_preview"
    preview_p2_dir = tmp_path / "analytics_preview_p2"
    preview_p3_dir = tmp_path / "analytics_preview_p3"
    preview_p4_dir = tmp_path / "analytics_preview_p4"
    preview_p5_dir = tmp_path / "analytics_preview_p5"
    seed_analytics_preview_bundle(preview_dir)
    seed_analytics_preview_p2_bundle(preview_p2_dir)
    seed_analytics_preview_p3_bundle(preview_p3_dir)
    seed_analytics_preview_p4_bundle(preview_p4_dir)
    seed_analytics_preview_p5_bundle(preview_p5_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_BUNDLE_DIR", str(preview_dir))
    monkeypatch.setenv("ANALYTICS_PREVIEW_P2_BUNDLE_DIR", str(preview_p2_dir))
    monkeypatch.setenv("ANALYTICS_PREVIEW_P3_BUNDLE_DIR", str(preview_p3_dir))
    monkeypatch.setenv("ANALYTICS_PREVIEW_P4_BUNDLE_DIR", str(preview_p4_dir))
    monkeypatch.setenv("ANALYTICS_PREVIEW_P5_BUNDLE_DIR", str(preview_p5_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register(admin_email, "pass1234")
    access_store.assign_role(email=admin_email)

    client = app.test_client()
    login_user(
        client,
        email=admin_email,
        password="pass1234",
        next_url="/admin/analytics-preview",
        follow_redirects=True,
    )

    hub_response = client.get("/admin/analytics-preview")
    p1_response = client.get("/admin/analytics-p1/today-model-info")
    p2_response = client.get("/admin/analytics-p2/portfolio-structure")
    p3_response = client.get("/admin/analytics-p3/model-quality")
    p4_response = client.get("/admin/analytics-p4/asset-exposure-detail")
    p5_response = client.get("/admin/analytics-p5/admin-ops-status")

    assert hub_response.status_code == 200
    hub_body = hub_response.get_data(as_text=True)
    assert "내부 Analytics Preview" in hub_body
    assert "포트폴리오 구조" in hub_body
    assert "보유 종목 이력" in hub_body
    assert "모델 품질" in hub_body
    assert "주간 브리핑" in hub_body
    assert "자산 노출 상세" in hub_body
    assert "변화 영향" in hub_body
    assert "Admin 운영 상태" in hub_body
    assert "Bundle Health" in hub_body
    assert p1_response.status_code == 200
    assert "오늘의 모델 정보" in p1_response.get_data(as_text=True)
    assert p2_response.status_code == 200
    assert "포트폴리오 구조" in p2_response.get_data(as_text=True)
    assert p3_response.status_code == 200
    assert "모델 품질" in p3_response.get_data(as_text=True)
    assert p4_response.status_code == 200
    assert "자산 노출 상세" in p4_response.get_data(as_text=True)
    assert p5_response.status_code == 200
    assert "Admin 운영 상태" in p5_response.get_data(as_text=True)


def test_internal_preview_bundle_rejects_publish_enabled_payload(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview"
    seed_analytics_preview_bundle(preview_dir, web_publish_enabled=True)
    monkeypatch.setenv("ANALYTICS_PREVIEW_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p1/today-model-info",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p1/today-model-info")

    assert response.status_code == 503
    assert "내부 preview 데이터를 읽지 못했습니다." in response.get_data(as_text=True)


def test_internal_preview_p2_pages_require_admin_and_render_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p2"
    seed_analytics_preview_p2_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P2_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/analytics-p2/portfolio-structure").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p2/portfolio-structure",
        follow_redirects=True,
    )

    portfolio_response = client.get("/admin/analytics-p2/portfolio-structure")
    lifecycle_response = client.get("/admin/analytics-p2/holding-lifecycle")

    assert portfolio_response.status_code == 200
    portfolio_body = portfolio_response.get_data(as_text=True)
    assert "포트폴리오 구조" in portfolio_body
    assert "최신 자산 구조" in portfolio_body
    assert "최근 26주 자산 구조 추이" in portfolio_body
    assert "현재 구성 비중" in portfolio_body
    assert "자산구조 주차 2026-03-20" in portfolio_body
    assert "Quant S3" in portfolio_body

    assert lifecycle_response.status_code == 200
    lifecycle_body = lifecycle_response.get_data(as_text=True)
    assert "보유 종목 이력" in lifecycle_body
    assert "현재 보유 종목 lifecycle" in lifecycle_body
    assert "장기 보유 종목" in lifecycle_body
    assert "최근 신규 편입 8주" in lifecycle_body
    assert "반영일 2026-03-24" in lifecycle_body
    assert "ISC" in lifecycle_body


def test_internal_preview_p2_bundle_rejects_publish_enabled_payload(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p2"
    seed_analytics_preview_p2_bundle(preview_dir, web_publish_enabled=True)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P2_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p2/portfolio-structure",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p2/portfolio-structure")

    assert response.status_code == 503
    assert "내부 preview 데이터를 읽지 못했습니다." in response.get_data(as_text=True)


def test_internal_preview_p3_pages_require_admin_and_render_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p3"
    seed_analytics_preview_p3_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P3_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/analytics-p3/model-quality").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p3/model-quality",
        follow_redirects=True,
    )

    quality_response = client.get("/admin/analytics-p3/model-quality")
    briefing_response = client.get("/admin/analytics-p3/weekly-briefing")

    assert quality_response.status_code == 200
    quality_body = quality_response.get_data(as_text=True)
    assert "모델 품질" in quality_body
    assert "최근 26주 품질 추이" in quality_body
    assert "최근 변화 밀도" in quality_body
    assert "상대강도 52W" in quality_body
    assert "품질 체크" in quality_body
    assert "최근 12주 성과 해석" in quality_body
    assert "최근 12주 누적수익률" in quality_body
    assert "상위 추정 기여 종목" in quality_body
    assert "삼성전자" in quality_body
    assert "재진입 분리" in quality_body
    assert "Quant S3" in quality_body

    assert briefing_response.status_code == 200
    briefing_body = briefing_response.get_data(as_text=True)
    assert "주간 브리핑" in briefing_body
    assert "브리핑 포인트" in briefing_body
    assert "상위 보유종목" in briefing_body
    assert "이번 주 변화" in briefing_body
    assert "최근 8주 변화" in briefing_body
    assert "최근 12주 성과 해석" in briefing_body
    assert "상위 추정 기여 종목" in briefing_body
    assert "평균 turnover 4W" in briefing_body
    assert "Top 5 비중" in briefing_body


def seed_analytics_preview_p4_bundle(
    bundle_dir: Path, *, web_publish_enabled: bool = False
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "asof": "2026-03-25",
        "internal_preview_only": True,
        "web_publish_enabled": web_publish_enabled,
        "bundle": "p4",
        "files": {
            "asset_exposure_detail": "asset_exposure_detail_20260325.json",
            "change_impact": "change_impact_20260325.json",
        },
    }
    asset_exposure_detail = {
        "meta": manifest,
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "latest_asset_detail": [
                    {"detail_bucket": "stock_equity", "bucket_weight": 0.6},
                    {"detail_bucket": "etf_bond", "bucket_weight": 0.2},
                    {"detail_bucket": "cash", "bucket_weight": 0.2},
                ],
                "asset_detail_trend_26w": [
                    {
                        "week_end": "2026-03-20",
                        "bucket_weights": {
                            "stock_equity": 0.6,
                            "etf_bond": 0.2,
                            "cash": 0.2,
                        },
                    }
                ],
                "latest_change_activity": {
                    "change_intensity_score": 41.2,
                    "change_intensity_label": "medium",
                    "event_count_total": 6,
                    "abs_delta_sum": 0.18,
                },
                "date_context": {
                    "asof_date": "2026-03-25",
                    "week_end": "2026-03-20",
                },
                "performance_interpretation": {
                    "window_weeks": 12,
                    "window_start_week_end": "2025-12-27",
                    "window_end_week_end": "2026-03-20",
                    "cumulative_return_12w": 0.19,
                    "best_weekly_return_12w": 0.06,
                    "best_weekly_return_week_end": "2026-02-21",
                    "worst_weekly_return_12w": -0.04,
                    "worst_weekly_return_week_end": "2026-01-31",
                    "positive_weeks_12w": 8,
                    "negative_weeks_12w": 3,
                    "flat_weeks_12w": 1,
                    "annualized_volatility_12w": 0.22,
                    "top_contributors_12w": [
                        {
                            "ticker": "005930",
                            "name": "삼성전자",
                            "estimated_contribution_12w": 0.04,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "estimated_contribution_12w": 0.03,
                        },
                    ],
                },
            }
        ],
    }
    change_impact = {
        "meta": manifest,
        "models": [
            {
                "model_code": "S3",
                "display_name": "Quant S3",
                "latest_change_activity": {
                    "new_count": 2,
                    "exit_count": 1,
                    "increase_count": 2,
                    "decrease_count": 1,
                    "event_count_total": 6,
                    "abs_delta_sum": 0.18,
                    "change_intensity_score": 41.2,
                    "change_intensity_label": "medium",
                },
                "change_activity_trend_26w": [
                    {
                        "week_end": "2026-03-20",
                        "new_count": 2,
                        "exit_count": 1,
                        "event_count_total": 6,
                        "abs_delta_sum": 0.18,
                        "change_intensity_score": 41.2,
                    }
                ],
                "impact_summary": {
                    "new_events_8w": 5,
                    "exit_events_8w": 4,
                    "avg_new_return_observed_8w": 0.031,
                    "avg_exit_return_observed_8w": -0.012,
                },
                "recent_new_entries_impact_8w": [
                    {
                        "event_week_end": "2026-03-20",
                        "ticker": "005930",
                        "name": "삼성전자",
                        "delta_weight": 0.03,
                        "holding_days_observed": 5,
                        "return_since_entry_observed": 0.021,
                        "outcome_status": "active",
                    }
                ],
                "recent_exits_impact_8w": [
                    {
                        "event_week_end": "2026-03-13",
                        "ticker": "000660",
                        "name": "SK하이닉스",
                        "delta_weight": -0.02,
                        "holding_days_observed": 12,
                        "return_since_entry_observed": -0.011,
                        "outcome_status": "exited",
                    }
                ],
                "date_context": {
                    "asof_date": "2026-03-25",
                    "week_end": "2026-03-20",
                },
                "performance_interpretation": {
                    "window_weeks": 12,
                    "window_start_week_end": "2025-12-27",
                    "window_end_week_end": "2026-03-20",
                    "cumulative_return_12w": 0.19,
                    "best_weekly_return_12w": 0.06,
                    "best_weekly_return_week_end": "2026-02-21",
                    "worst_weekly_return_12w": -0.04,
                    "worst_weekly_return_week_end": "2026-01-31",
                    "positive_weeks_12w": 8,
                    "negative_weeks_12w": 3,
                    "flat_weeks_12w": 1,
                    "annualized_volatility_12w": 0.22,
                    "top_contributors_12w": [
                        {
                            "ticker": "005930",
                            "name": "삼성전자",
                            "estimated_contribution_12w": 0.04,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "estimated_contribution_12w": 0.03,
                        },
                    ],
                },
            }
        ],
    }
    (bundle_dir / "bundle_manifest_20260325.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "asset_exposure_detail_20260325.json").write_text(
        json.dumps(asset_exposure_detail, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "change_impact_20260325.json").write_text(
        json.dumps(change_impact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_analytics_preview_p5_bundle(
    bundle_dir: Path, *, web_publish_enabled: bool = False
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "asof": "2026-03-25",
        "internal_preview_only": True,
        "web_publish_enabled": web_publish_enabled,
        "bundle": "p5",
        "bundle_version": "analytics-preview-v5",
        "schema_version": "2026-03-26",
        "built_at_utc": "2026-03-26T02:39:39Z",
        "build_status": "ok",
        "file_meta": {
            "admin_ops_status": {
                "path": "admin_ops_status_20260325.json",
                "exists": True,
                "size_bytes": 1024,
                "md5": "abc123ops",
            },
            "bundle_health": {
                "path": "bundle_health_20260325.json",
                "exists": True,
                "size_bytes": 2048,
                "md5": "abc123health",
            },
        },
        "files": {
            "admin_ops_status": "admin_ops_status_20260325.json",
            "bundle_health": "bundle_health_20260325.json",
        },
    }
    admin_ops_status = {
        "meta": {
            **manifest,
            "freshness": {
                "asof": "2026-03-25",
                "analytics_db_mtime_utc": "2026-03-26T02:39:39Z",
                "latest_week_end": "2026-03-27",
                "latest_change_week_end": "2026-03-27",
                "latest_quality_week_end": "2026-03-27",
            },
        },
        "status": {
            "overall_status": "ok",
            "bundle_count": 5,
            "bundles_ok": 5,
            "recommendation": "all preview bundles are ready",
        },
    }
    bundle_health = {
        "meta": manifest,
        "bundles": [
            {
                "bundle": "p4",
                "expected_pages": ["asset_exposure_detail", "change_impact"],
                "manifest_exists": True,
                "build_status": "ok",
                "files_ok": True,
                "built_at_utc": "2026-03-26T02:39:31Z",
                "latest_week_end": "2026-03-27",
                "schema_version": "2026-03-26",
                "bundle_version": "analytics-preview-v5",
            },
            {
                "bundle": "p5",
                "expected_pages": ["admin_ops_status", "bundle_health"],
                "manifest_exists": True,
                "build_status": "ok",
                "files_ok": True,
                "built_at_utc": "2026-03-26T02:39:39Z",
                "latest_week_end": "2026-03-27",
                "schema_version": "2026-03-26",
                "bundle_version": "analytics-preview-v5",
            },
        ],
    }
    (bundle_dir / "bundle_manifest_20260325.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "admin_ops_status_20260325.json").write_text(
        json.dumps(admin_ops_status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "bundle_health_20260325.json").write_text(
        json.dumps(bundle_health, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_internal_preview_p4_routes_render_bundle(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p4"
    seed_analytics_preview_p4_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P4_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p4/asset-exposure-detail",
        follow_redirects=True,
    )

    exposure_response = client.get("/admin/analytics-p4/asset-exposure-detail")
    impact_response = client.get("/admin/analytics-p4/change-impact")

    assert exposure_response.status_code == 200
    exposure_body = exposure_response.get_data(as_text=True)
    assert "자산 노출 상세" in exposure_body
    assert "최신 자산 노출" in exposure_body
    assert "최근 26주 자산 노출 추이" in exposure_body
    assert "세부 bucket 구성" in exposure_body
    assert "stock_equity" in exposure_body

    assert impact_response.status_code == 200
    impact_body = impact_response.get_data(as_text=True)
    assert "변화 영향" in impact_body
    assert "최근 26주 변화 강도" in impact_body
    assert "영향 요약" in impact_body
    assert "비중 확대" in impact_body
    assert "비중 축소" in impact_body


def test_internal_preview_p5_routes_render_bundle(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p5"
    seed_analytics_preview_p5_bundle(preview_dir)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P5_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p5/admin-ops-status",
        follow_redirects=True,
    )

    ops_response = client.get("/admin/analytics-p5/admin-ops-status")
    health_response = client.get("/admin/analytics-p5/bundle-health")

    assert ops_response.status_code == 200
    ops_body = ops_response.get_data(as_text=True)
    assert "Admin 운영 상태" in ops_body
    assert "운영 권고" in ops_body
    assert "빌드 메타" in ops_body
    assert "bundle version" in ops_body

    assert health_response.status_code == 200
    health_body = health_response.get_data(as_text=True)
    assert "Bundle Health" in health_body
    assert "p4" in health_body
    assert "p5" in health_body
    assert "파일 메타" in health_body
    assert "abc123ops" in health_body


def test_internal_preview_p4_bundle_rejects_publish_enabled_payload(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p4"
    seed_analytics_preview_p4_bundle(preview_dir, web_publish_enabled=True)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P4_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p4/asset-exposure-detail",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p4/asset-exposure-detail")

    assert response.status_code == 503
    assert "내부 preview 데이터를 읽지 못했습니다." in response.get_data(as_text=True)


def test_internal_preview_p5_bundle_rejects_publish_enabled_payload(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p5"
    seed_analytics_preview_p5_bundle(preview_dir, web_publish_enabled=True)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P5_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p5/admin-ops-status",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p5/admin-ops-status")

    assert response.status_code == 503
    assert "내부 preview 데이터를 읽지 못했습니다." in response.get_data(as_text=True)


def seed_admin_market_lab_bundle(
    bundle_dir: Path,
    *,
    visibility: str = "admin_only_pre_publish",
    include_intraday: bool = True,
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "market": "KR",
        "asof": "2026-03-25T22:43:02+09:00",
        "visibility": visibility,
        "title": "QuantMarket admin market payload manifest",
        "files": {
            "timeline": "admin_market_timeline.json",
            "asset_strength": "admin_market_asset_strength.json",
            "state_transition": "admin_market_state_transition.json",
            "model_background": "admin_market_model_background.json",
            "manifest": "admin_market_manifest.json",
            "intraday_summary": "admin_market_intraday_summary.json",
            "intraday_detail": "admin_market_intraday_detail.json",
            "intraday_manifest": "admin_market_intraday_manifest.json",
        },
    }
    timeline = {
        "market": "KR",
        "asof": manifest["asof"],
        "current_state": {
            "asof": manifest["asof"],
            "state_label": "상승",
            "state_score": 1.11,
            "state_change_direction": "stronger",
            "trend_score": 3.0,
            "breadth_score": 2.28,
            "risk_score": -3.0,
            "defensive_flow_score": -0.13,
            "total_score": 1.11,
        },
        "points": [
            {
                "asof": manifest["asof"],
                "state_label": "상승",
                "state_score": 1.11,
                "state_change_direction": "stronger",
                "trend_score": 3.0,
                "breadth_score": 2.28,
                "risk_score": -3.0,
                "defensive_flow_score": -0.13,
                "total_score": 1.11,
            }
        ],
    }
    asset_strength = {
        "market": "KR",
        "asof": manifest["asof"],
        "current_assets": [
            {
                "asset_group": "KOSPI",
                "ret_20d": 0.12,
                "strength_score": 2.11,
                "strength_rank": 1,
                "strength_label": "강함",
            },
            {
                "asset_group": "GOLD",
                "ret_20d": -0.03,
                "strength_score": -0.81,
                "strength_rank": 6,
                "strength_label": "약함",
            },
        ],
        "rank_history": [
            {
                "asof": manifest["asof"],
                "asset_group": "KOSPI",
                "strength_rank": 1,
                "strength_score": 2.11,
                "strength_label": "강함",
            },
            {
                "asof": manifest["asof"],
                "asset_group": "GOLD",
                "strength_rank": 6,
                "strength_score": -0.81,
                "strength_label": "약함",
            },
        ],
    }
    state_transition = {
        "market": "KR",
        "asof": manifest["asof"],
        "current": {
            "current_state": "상승",
            "prev_state": "강보합",
            "duration_hours": 12.7,
            "transition_count_5d": 4,
            "transition_count_20d": 4,
            "stability_score": 0.57,
        },
        "recent_changes": [
            {
                "asof": manifest["asof"],
                "state_label": "상승",
                "prev_state_label": "강보합",
                "state_change_direction": "stronger",
                "state_score": 1.11,
            }
        ],
    }
    model_background = {
        "market": "KR",
        "asof": manifest["asof"],
        "state_label": "상승",
        "state_score": 1.11,
        "summary_line": "상승 흐름이 우세합니다.",
        "reference_note": "내부 breadth와 변동성 지표를 함께 봅니다.",
        "briefing_tone": "위험선호 환경",
        "model_background_points": ["상승 흐름 우세", "breadth 개선"],
        "favorable_signals": ["코스피 강세"],
        "caution_signals": ["달러 강세"],
        "top_assets": [asset_strength["current_assets"][0]],
        "bottom_assets": [asset_strength["current_assets"][1]],
    }
    intraday_manifest = {
        "market": "KR",
        "asof": manifest["asof"],
        "visibility": visibility,
        "title": "QuantMarket admin intraday manifest",
        "files": {
            "summary": "admin_market_intraday_summary.json",
            "detail": "admin_market_intraday_detail.json",
        },
    }
    intraday_summary = {
        "market": "KR",
        "asof": manifest["asof"],
        "session_status": "live",
        "reference_close_date": "2026-03-25",
        "direction_label": "강한 약세",
        "total_score": -2.34,
        "summary_line": "프로그램과 주요 투자주체 흐름은 순매도 우위입니다.",
        "indexes": [
            {"index_code": "1001", "index_name": "KOSPI", "price": 5453.01, "change_pct": -0.0335},
            {"index_code": "2001", "index_name": "KOSDAQ", "price": 1135.96, "change_pct": 0.0129},
        ],
        "fx": [
            {
                "series_code": "USDKRW",
                "series_name": "USD/KRW",
                "price": 1506.28,
                "change_pct": 0.0028,
            }
        ],
        "futures": [
            {
                "contract_code": "FUT",
                "contract_name": "선물(2606)",
                "price": 809.10,
                "change_pct": -0.0384,
                "volume": 161975.0,
            }
        ],
        "flow_signals": [
            {
                "signal_code": "PROGRAM_TOTAL_NET",
                "signal_name": "프로그램 전체 순매수",
                "metric_value": -16251.0,
                "metric_unit": "억원",
                "direction_label": "순매도 우위",
                "strength_label": "강함",
            },
            {
                "signal_code": "FOREIGNER_NET",
                "signal_name": "외국인 순매수",
                "metric_value": -30980.0,
                "metric_unit": "억원",
                "direction_label": "순매도 우위",
                "strength_label": "강함",
            },
        ],
        "signal_overlay": {
            "futures_overlay": {"relative_label": "현물과 유사", "source": "naver:sise_index:FUT"},
            "flow_overlay": {"messages": ["프로그램과 주요 투자주체 흐름은 순매도 우위입니다."]},
        },
    }
    intraday_detail = {
        "market": "KR",
        "asof": manifest["asof"],
        "session_status": "live",
        "reference_close_date": "2026-03-25",
        "state": {
            "asof": manifest["asof"],
            "session_status": "live",
            "direction_label": "강한 약세",
            "total_score": -2.34,
            "summary_line": "외국인 순매도가 큰 편이라 장중 부담 요인으로 읽힙니다.",
            "reference_close_date": "2026-03-25",
        },
        "breadth": [{"universe_code": "KOSPI", "adv_dec_ratio": 0.53, "positive_ratio": 0.33}],
        "flow_signals": intraday_summary["flow_signals"],
        "futures": intraday_summary["futures"],
        "signal_overlay": {
            "futures_overlay": {
                "relative_label": "현물과 유사",
                "source": "naver:sise_index:FUT",
            },
            "flow_overlay": {
                "messages": [
                    "프로그램과 주요 투자주체 흐름은 순매도 우위입니다.",
                    "외국인 순매도가 큰 편이라 장중 부담 요인으로 읽힙니다.",
                ]
            },
            "futures_source": "naver:sise_index:FUT",
            "flow_source": "naver:programDealTrendTime+investorDealTrendTime",
            "futures_available": True,
            "flow_available": True,
        },
        "description": "장중 참고용 현재 지표 스냅샷입니다.",
        "notice": "장중 수치는 종가 확정 전 참고 정보입니다.",
    }
    (bundle_dir / "admin_market_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "admin_market_timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "admin_market_asset_strength.json").write_text(
        json.dumps(asset_strength, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "admin_market_state_transition.json").write_text(
        json.dumps(state_transition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "admin_market_model_background.json").write_text(
        json.dumps(model_background, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if include_intraday:
        (bundle_dir / "admin_market_intraday_manifest.json").write_text(
            json.dumps(intraday_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (bundle_dir / "admin_market_intraday_summary.json").write_text(
            json.dumps(intraday_summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (bundle_dir / "admin_market_intraday_detail.json").write_text(
            json.dumps(intraday_detail, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def test_internal_preview_p3_bundle_rejects_publish_enabled_payload(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    preview_dir = tmp_path / "analytics_preview_p3"
    seed_analytics_preview_p3_bundle(preview_dir, web_publish_enabled=True)
    monkeypatch.setenv("ANALYTICS_PREVIEW_P3_BUNDLE_DIR", str(preview_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/analytics-p3/model-quality",
        follow_redirects=True,
    )

    response = client.get("/admin/analytics-p3/model-quality")

    assert response.status_code == 503
    assert "내부 preview 데이터를 읽지 못했습니다." in response.get_data(as_text=True)


def test_admin_market_briefing_lab_requires_admin_and_renders_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    bundle_dir = tmp_path / "admin_market_lab"
    seed_admin_market_lab_bundle(bundle_dir)
    monkeypatch.setenv("ADMIN_MARKET_LAB_DIR", str(bundle_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")
    access_store.authenticate_or_register("member@example.com", "pass1234")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/market-briefing-lab").status_code == 404

    user_client = app.test_client()
    login_user(
        user_client,
        email="member@example.com",
        password="pass1234",
        next_url="/admin/market-briefing-lab",
        follow_redirects=True,
    )
    assert user_client.get("/admin/market-briefing-lab").status_code == 404

    admin_client = app.test_client()
    login_user(
        admin_client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/market-briefing-lab",
        follow_redirects=True,
    )

    response = admin_client.get("/admin/market-briefing-lab")
    raw_response = admin_client.get("/admin/market-briefing-lab/raw/timeline")
    intraday_raw = admin_client.get("/admin/market-briefing-lab/raw/intraday_summary")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "시장 브리핑 Lab" in body
    assert "현재 시장상태 요약" in body
    assert "장중 현재 지표" in body
    assert "선물 참고" in body
    assert "장중 수급 참고" in body
    assert "현물과 유사" in body
    assert "프로그램 전체 순매수" in body
    assert "모델 해석 백그라운드" in body
    assert "자산군 상대강도" in body
    assert "상태 전이 브리핑" in body
    assert raw_response.status_code == 200
    assert raw_response.get_json()["current_state"]["state_label"] == "상승"
    assert intraday_raw.status_code == 200
    assert intraday_raw.get_json()["session_status"] == "live"


def test_admin_market_briefing_lab_gracefully_hides_intraday_when_missing(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    bundle_dir = tmp_path / "admin_market_lab"
    seed_admin_market_lab_bundle(bundle_dir, include_intraday=False)
    monkeypatch.setenv("ADMIN_MARKET_LAB_DIR", str(bundle_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/market-briefing-lab",
        follow_redirects=True,
    )

    response = client.get("/admin/market-briefing-lab")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "현재 시장상태 요약" in body
    assert "장중 현재 지표" not in body


def test_https_requests_include_hsts_header(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/login", base_url="https://redbot.co.kr")

    assert response.status_code == 200
    assert response.headers["Strict-Transport-Security"] == "max-age=2592000"


def test_admin_market_briefing_lab_rejects_invalid_visibility(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False, internal_preview_enabled=True)
    bundle_dir = tmp_path / "admin_market_lab"
    seed_admin_market_lab_bundle(bundle_dir, visibility="public")
    monkeypatch.setenv("ADMIN_MARKET_LAB_DIR", str(bundle_dir))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/market-briefing-lab",
        follow_redirects=True,
    )

    response = client.get("/admin/market-briefing-lab")

    assert response.status_code == 503
    assert "admin market data unavailable" in response.get_data(as_text=True)


def seed_admin_new_entry_tracker_payload(target_path: Path) -> None:
    payload = {
        "source_name": "handoff:admin_new_entry_tracker",
        "schema_version": "v1",
        "visibility": "admin_only",
        "as_of_date": "2026-04-14",
        "generated_at": "2026-04-14T22:10:31",
        "freshness": {
            "user_latest_asof": "2026-04-03",
            "internal_latest_week_end": "2026-04-10",
            "tstock_latest_event_date": "2026-04-10",
            "tetf_latest_event_date": "2026-04-10",
        },
        "summary": {
            "user_models": [
                {"service_profile": "stable", "event_type": "new_entry", "count": 1},
            ],
            "internal_models": [
                {"model_code": "S2", "event_type": "new_entry", "count": 1},
                {
                    "model_code": "I-STOCK-STRONG-RSI-V01",
                    "event_type": "new_entry",
                    "count": 1,
                },
            ],
            "tseries_models": [
                {"model_code": "T-STOCK-V01", "event_type": "promotion", "count": 1},
            ],
        },
        "user_models": [
            {
                "scope": "user",
                "service_profile": "stable",
                "user_model_name": "안정형",
                "model_key": "stable",
                "event_type": "new_entry",
                "event_date": "2026-04-10",
                "week_end": "2026-04-10",
                "security_code": "005930",
                "display_name": "삼성전자",
                "delta_weight": 0.01,
                "curr_weight": 0.01,
                "is_current": True,
                "forward_returns": {"1w": 0.03, "2w": None, "1m": None, "3m": None},
                "current_return": 0.05,
            }
        ],
        "internal_models": [
            {
                "scope": "internal",
                "model_code": "S2",
                "event_type": "new_entry",
                "event_date": "2026-04-10",
                "week_end": "2026-04-10",
                "security_code": "005930",
                "display_name": "삼성전자",
                "delta_weight": 0.12,
                "curr_weight": 0.12,
                "is_current": False,
                "forward_returns": {"1w": 0.02, "2w": -0.01, "1m": None, "3m": None},
                "forward_risk_metrics": {"1m": {"mdd": -0.051393, "sharpe": 5.716243}},
                "current_risk_metrics": {"mdd": -0.02, "sharpe": 1.23},
                "current_return": 0.05,
            },
            {
                "scope": "internal",
                "model_code": "S2",
                "event_type": "new_entry",
                "event_date": "2025-11-14",
                "week_end": "2025-11-14",
                "security_code": "003540",
                "display_name": "대신증권",
                "delta_weight": 0.12,
                "curr_weight": 0.12,
                "is_current": False,
                "forward_returns": {"1w": 0.20, "2w": 0.30, "1m": 0.40, "3m": 0.50},
                "current_return": 0.90,
            },
            {
                "scope": "internal",
                "model_code": "I-STOCK-STRONG-RSI-V01",
                "event_type": "new_entry",
                "event_date": "2026-05-04",
                "week_end": "2026-05-04",
                "security_code": "033100",
                "display_name": "제룡전기",
                "delta_weight": 0.0,
                "curr_weight": None,
                "rank_no": 1,
                "score": 125.0,
                "score_basis": "i_raw_score",
                "universe_rank_no": 1,
                "universe_rank_score": 125.0,
                "display_score": 125.0,
                "is_current": True,
                "forward_returns": {"1w": 0.02, "2w": 0.03, "1m": None, "3m": None},
                "current_return": 0.05,
            },
        ],
        "tseries_models": [
            {
                "scope": "tseries",
                "model_code": "T-STOCK-V01",
                "event_type": "promotion",
                "event_date": "2026-04-10",
                "week_end": "2026-04-10",
                "security_code": "000660",
                "display_name": "SK하이닉스",
                "delta_weight": None,
                "curr_weight": None,
                "is_current": True,
                "forward_returns": {"1w": 0.07, "2w": 0.08, "1m": None, "3m": None},
                "current_return": 0.09,
            }
        ],
        "weekly_rankings": {
            "user_models": [
                {
                    "week_end": "2026-05-04",
                    "snapshot_date": "2026-05-04",
                    "service_profile": "stable",
                    "user_model_name": "안정형",
                    "security_code": "005930",
                    "display_name": "삼성전자",
                    "rank_no": 1,
                    "score": 0.12,
                    "score_basis": "target_weight_proxy",
                    "weight": 0.12,
                    "is_latest_snapshot": True,
                }
            ],
            "internal_models": [
                {
                    "week_end": "2026-04-10",
                    "snapshot_date": "2026-04-10",
                    "model_code": "S2",
                    "security_code": "005930",
                    "display_name": "삼성전자",
                    "rank_no": 3,
                    "score": 0.44,
                    "score_basis": "alpha_score",
                    "weight": 0.12,
                    "is_latest_snapshot": True,
                },
                {
                    "week_end": "2025-11-14",
                    "snapshot_date": "2025-11-14",
                    "model_code": "S2",
                    "security_code": "003540",
                    "display_name": "대신증권",
                    "rank_no": 1,
                    "score": 0.99,
                    "score_basis": "alpha_score",
                    "weight": 0.12,
                    "is_latest_snapshot": False,
                },
                {
                    "week_end": "2026-04-10",
                    "snapshot_date": "2026-04-10",
                    "model_code": "I-STOCK-STRONG-RSI-V01",
                    "security_code": "033100",
                    "display_name": "제룡전기",
                    "rank_no": 1,
                    "score": 125.0,
                    "score_basis": "i_raw_score",
                    "weight": None,
                    "universe_rank_no": 1,
                    "universe_rank_score": 125.0,
                    "display_score": 125.0,
                    "is_latest_snapshot": True,
                },
            ],
            "tseries_models": [
                {
                    "week_end": "2026-04-10",
                    "snapshot_date": "2026-04-10",
                    "model_code": "T-STOCK-V01",
                    "security_code": "000660",
                    "display_name": "SK하이닉스",
                    "rank_no": 2,
                    "score": 0.73,
                    "score_basis": "stage_blend",
                    "weight": None,
                    "candidate_bucket": "near",
                    "stage1_prob": 0.69,
                    "stage2_prob": 0.57,
                    "is_latest_snapshot": True,
                }
            ],
        },
        "model_performance_summary": {
            "internal_models": [
                {
                    "model_code": "I-STOCK-STRONG-RSI-V01",
                    "cagr": 0.42,
                    "mdd_1y": -0.12,
                    "sharpe_1y": 1.8,
                    "trailing_1w": 0.02,
                    "trailing_2w": 0.04,
                    "trailing_1m": 0.06,
                    "trailing_3m": 0.11,
                    "trailing_6m": 0.18,
                    "trailing_1y": 0.31,
                    "itd_return": 0.56,
                    "metric_basis": "i_series_shadow",
                    "sample_count": 30,
                }
            ]
        },
        "actual_live_performance_summary": {
            "metric_basis": "actual_market_price_forward_return_since_live_start",
            "description": "운영 시작 이후 모델 편입 종목의 실제 시장가격 추적 결과",
            "horizons": ["current_return", "1w", "2w", "1m", "2m", "3m", "6m", "1y"],
            "user_models": [
                {
                    "service_profile": "stable",
                    "user_model_name": "안정형",
                    "live_start_date": "2026-03-18",
                    "source_event_count": 3,
                    "live_event_count": 1,
                    "latest_live_event_date": "2026-04-10",
                    "metric_basis": "actual_market_price_forward_return_since_live_start",
                    "metrics": {
                        "current_return": {
                            "sample_count": 1,
                            "avg_return": 0.05,
                            "median_return": 0.05,
                            "win_rate": 1.0,
                        },
                        "1w": {
                            "sample_count": 0,
                            "avg_return": None,
                            "median_return": None,
                            "win_rate": None,
                        },
                        "1m": {
                            "sample_count": 1,
                            "avg_return": 0.267127,
                            "median_return": 0.267127,
                            "win_rate": 1.0,
                            "mdd_sample_count": 1,
                            "avg_mdd": -0.051393,
                            "median_mdd": -0.051393,
                            "sharpe_sample_count": 1,
                            "avg_sharpe": 5.716243,
                            "median_sharpe": 5.716243,
                        },
                        "2m": {
                            "sample_count": 0,
                            "avg_return": None,
                            "median_return": None,
                            "win_rate": None,
                        },
                    },
                }
            ],
            "internal_models": [
                {
                    "model_code": "S2",
                    "live_start_date": "2026-03-12",
                    "source_event_count": 5,
                    "live_event_count": 2,
                    "latest_live_event_date": "2026-04-10",
                    "metric_basis": "actual_market_price_forward_return_since_live_start",
                    "metrics": {
                        "current_return": {
                            "sample_count": 2,
                            "avg_return": 0.04,
                            "median_return": 0.03,
                            "win_rate": 0.5,
                        }
                    },
                },
                {
                    "model_code": "I-STOCK-STRONG-RSI-V01",
                    "live_start_date": "2026-04-29",
                    "source_event_count": 1,
                    "live_event_count": 0,
                    "latest_live_event_date": "",
                    "metric_basis": "actual_market_price_forward_return_since_live_start",
                    "metrics": {
                        "current_return": {
                            "sample_count": 0,
                            "avg_return": None,
                            "median_return": None,
                            "win_rate": None,
                        }
                    },
                },
            ],
            "tseries_models": [
                {
                    "model_code": "T-STOCK-V01",
                    "live_start_date": "2026-04-01",
                    "source_event_count": 4,
                    "live_event_count": 1,
                    "latest_live_event_date": "2026-04-10",
                    "metric_basis": "actual_market_price_forward_return_since_live_start",
                    "metrics": {
                        "current_return": {
                            "sample_count": 1,
                            "avg_return": 0.09,
                            "median_return": 0.09,
                            "win_rate": 1.0,
                        }
                    },
                }
            ],
        },
    }
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_valuation_ai_payloads(current_path: Path, performance_path: Path) -> None:
    current_payload = {
        "source_name": "valuation_ai_challenger_current",
        "schema_version": "1.0",
        "visibility": "admin_only",
        "model_code": "AI-GROWTH-VALUATION-V01",
        "as_of_date": "2026-05-04",
        "generated_at": "2026-05-06T19:39:04",
        "champion": {
            "feature_set": "LOCAL_MARKET",
            "model_version": "AI-GROWTH-VALUATION-V01-LOCAL-MARKET-20260504-001",
            "description": "기존 LOCAL_MARKET 기준 champion입니다.",
            "feature_count": 43,
        },
        "challenger": {
            "feature_set": "QM_MARKET_THEME",
            "model_version": "AI-GROWTH-VALUATION-V01-QM-MARKET-THEME-20260504-001",
            "description": "QuantMarket 테마 context를 반영한 challenger입니다.",
            "feature_count": 51,
        },
        "risk_overlay": {
            "feature_set": "QM_MARKET_RISK",
            "model_version": "AI-GROWTH-VALUATION-V01-QM-MARKET-RISK-20260504-001",
            "description": "risk_tag/caution tag 제공용 overlay입니다.",
            "feature_count": 49,
        },
        "summary_by_model": [
            {
                "scope": "internal",
                "model_code": "I-STOCK-STRONG-RSI-V01",
                "candidate_count": 1,
                "challenger_favorable_count": 1,
                "challenger_caution_count": 0,
                "challenger_upgrade_count": 1,
                "challenger_downgrade_count": 0,
                "risk_caution_count": 1,
                "risk_watch_count": 0,
            }
        ],
        "candidates": [
            {
                "scope": "internal",
                "model_code": "I-STOCK-STRONG-RSI-V01",
                "security_code": "033100",
                "display_name": "제룡전기",
                "rank_no": 1,
                "score": 125.0,
                "score_basis": "i_raw_score",
                "champion_state": "neutral",
                "champion_score": 0.42,
                "challenger_state": "favorable",
                "challenger_score": 0.61,
                "challenger_change_label": "upgrade",
                "risk_tag": "caution",
                "risk_state": "watch",
                "risk_score": 0.33,
                "qm_quantmarket_theme_bucket": "power_grid",
                "qm_theme_momentum_score": 0.77,
                "qm_theme_rotation_score": 0.66,
                "qm_risk_score": None,
                "qm_market_stress_score": 0.12,
            }
        ],
    }
    performance_payload = {
        "source_name": "valuation_ai_challenger_shadow_performance",
        "schema_version": "1.0",
        "visibility": "admin_only",
        "model_code": "AI-GROWTH-VALUATION-V01",
        "source_as_of_date": "2026-05-04",
        "performance_asof_date": "2026-05-04",
        "generated_at": "2026-05-06T19:40:23",
        "metric_basis": "live_price_tracking_after_candidate_snapshot",
        "horizons": ["current", "1w", "2w", "1m"],
        "summary": [
            {
                "group_type": "challenger_state",
                "group_value": "favorable",
                "horizon": "current",
                "candidate_count": 1,
                "sample_count": 1,
                "avg_return": 0.032,
                "median_return": 0.032,
                "win_rate": 1.0,
                "avg_mdd": -0.01,
                "avg_sharpe": None,
            }
        ],
        "detail": [
            {
                "security_code": "033100",
                "display_name": "제룡전기",
                "track_start_date": "2026-05-04",
                "champion_state": "neutral",
                "challenger_state": "favorable",
                "risk_tag": "caution",
                "live_current_return": 0.032,
                "live_ret_1w": None,
                "live_ret_2w": None,
                "live_ret_1m": None,
                "live_current_mdd": -0.01,
                "live_current_sharpe": None,
            }
        ],
    }
    learning_payload = {
        "source_name": "ai_learning_models_current",
        "schema_version": "1.0",
        "visibility": "admin_only",
        "as_of_date": "2026-05-08",
        "generated_at": "2026-05-10T20:50:11",
        "models": [
            {
                "model_code": "AI-CANDIDATE-VALIDATION-V01",
                "model_name_ko": "퀀트후보검증AI",
                "model_role": "candidate_validation_shadow",
                "status": "pending_samples",
                "as_of_date": "2026-05-08",
                "summary": {
                    "trained_models": 1,
                    "fallback_models": 1,
                    "horizon_status": [{"horizon": "1w", "sample_count": 0, "available": False}],
                },
            },
            {
                "model_code": "AI-GROWTH-VALUATION-V01",
                "model_name_ko": "주가수준평가AI",
                "model_role": "valuation_reference_challenger_shadow",
                "status": "available",
                "as_of_date": "2026-05-08",
                "performance_asof_date": "2026-05-08",
                "summary": {"candidate_count": 1, "monitor_status": None},
            },
            {
                "model_code": "AI-DOWNSIDE-RISK-V01",
                "model_name_ko": "하락위험예측AI",
                "model_role": "downside_risk_overlay_shadow",
                "status": "available",
                "as_of_date": "2026-05-08",
                "performance_asof_date": "2026-05-08",
                "summary": {
                    "auc": 0.57855,
                    "train_rows": 14607,
                    "valid_rows": 5337,
                    "tag_counts": [{"downside_risk_tag": "risk_caution", "count": 5}],
                    "tracker_roles": ["common_champion"],
                },
            },
            {
                "model_code": "AI-CANDIDATE-RANK-DELTA-V01",
                "model_name_ko": "후보순위변화AI",
                "model_role": "candidate_rank_delta_shadow",
                "status": "available",
                "as_of_date": "2026-05-08",
                "summary": {"candidate_count": 7},
            },
            {
                "model_code": "AI-THEME-PERSISTENCE-V01",
                "model_name_ko": "테마지속성AI",
                "model_role": "theme_persistence_shadow",
                "status": "available",
                "as_of_date": "2026-05-08",
                "summary": {"feature_mode": "BASE"},
            },
            {
                "model_code": "AI-ETF-SHADOW-PORTFOLIO-V01",
                "model_name_ko": "ETF전용포트폴리오AI",
                "model_role": "etf_shadow_portfolio",
                "status": "shadow_observation",
                "as_of_date": "2026-05-08",
                "summary": {"selected_role": "CORE_BETA", "holding_count": 1},
            },
        ],
    }
    candidate_validation_payload = {
        "source_name": "ai_shadow_observation",
        "visibility": "admin_only",
        "model_code": "AI-CANDIDATE-VALIDATION-V01",
        "model_name_ko": "퀀트후보검증AI",
        "as_of_date": "2026-05-08",
        "generated_at": "2026-05-10T16:31:38",
        "model_specific_training": {
            "trained_models": [
                {
                    "scope_key": "internal",
                    "model_id": "S2",
                    "label": "label_quality_1m",
                    "auc": 0.53236,
                    "top30_avg_1m_return": 0.030446,
                    "top30_win_rate": 0.5,
                }
            ],
            "fallback_models": [
                {
                    "scope_key": "user",
                    "model_id": "stable",
                    "label_rows": 16,
                    "reason": "insufficient_model_specific_labels",
                }
            ],
        },
        "reconstructed_summary": {
            "reconstructed_model_specific_tag_1m": [
                {
                    "group_value": "MS_CONFIRM",
                    "sample_count": 1,
                    "avg_return": 0.1,
                    "win_rate": 1.0,
                    "avg_mdd": -0.01,
                }
            ]
        },
        "live_summary": {
            "status": "pending_samples",
            "horizon_status": [{"horizon": "1w", "sample_count": 0, "available": False}],
        },
        "latest_shadow_sample": [{"ticker": "005930", "name": "삼성전자"}],
    }
    valuation_monitor_payload = {
        "source_name": "valuation_ai_shadow_monitor",
        "visibility": "admin_only",
        "availability": [
            {
                "horizon": "current",
                "candidate_count": 1,
                "sample_count": 1,
                "avg_return": 0.032,
                "win_rate": 1.0,
            },
            {
                "horizon": "1w",
                "candidate_count": 1,
                "sample_count": 0,
                "avg_return": "NaN",
                "win_rate": "NaN",
            },
        ],
        "state_counts": {
            "challenger": {"favorable": 1},
            "risk_tag": {"caution": 1},
        },
    }
    downside_current_payload = {
        "source_name": "downside_risk_ai_current",
        "visibility": "admin_only",
        "model_code": "AI-DOWNSIDE-RISK-V01",
        "model_name_ko": "하락위험예측AI",
        "model_version": "AI-DOWNSIDE-RISK-V01_20260508_001",
        "evaluation": {"auc": 0.57855, "train_rows": 14607, "valid_rows": 5337},
        "tag_counts": [{"downside_risk_tag": "risk_caution", "count": 5}],
        "top_risk_candidates": [
            {
                "scope_key": "user",
                "model_id": "growth",
                "ticker": "010170",
                "name": "대한광통신",
                "downside_risk_prob": 0.754188,
                "downside_risk_tag": "risk_exit_watch",
                "action_hint": "매도/비중축소 후보 관찰",
                "ret_20d": 0.880978,
                "mdd_20d": -0.28933,
            }
        ],
    }
    downside_tracker_payload = {
        "source_name": "downside_risk_ai_shadow_tracker",
        "visibility": "admin_only",
        "tracker_roles": ["common_champion"],
        "summary": [
            {
                "group_type": "risk_tag",
                "group_value": "risk_caution",
                "horizon": "1w",
                "candidate_count": 5,
                "sample_count": 0,
                "avg_return": None,
                "median_return": None,
                "win_rate": None,
                "avg_mdd": None,
                "bad_return_rate": None,
            }
        ],
        "detail_sample": [],
    }
    theme_persistence_payload = {
        "source_name": "theme_persistence_ai_current",
        "schema_version": "1.0",
        "visibility": "admin_only",
        "model_code": "AI-THEME-PERSISTENCE-V01",
        "model_name_ko": "테마지속성AI",
        "model_version": "AI-THEME-PERSISTENCE-V01_20260508_001",
        "model_role": "theme_persistence_shadow",
        "as_of_date": "2026-05-08",
        "generated_at": "2026-05-11T16:38:39",
        "feature_mode": "BASE",
        "evaluation": [
            {
                "label": "label_theme_continue_1m",
                "head": "continue",
                "auc": 0.714944,
                "top30_label_rate": 1.0,
                "bottom30_label_rate": 0.166667,
                "top30_future_theme_ret_1m": 0.062894,
            },
            {
                "label": "label_theme_fade_1m",
                "head": "fade",
                "auc": 0.772875,
                "top30_label_rate": 0.366667,
                "bottom30_label_rate": 0.0,
                "top30_future_theme_ret_1m": 0.036397,
            },
        ],
        "tag_counts": [
            {"theme_persistence_tag": "theme_persist_strong", "count": 3},
            {"theme_persistence_tag": "theme_persist_watch", "count": 3},
            {"theme_persistence_tag": "theme_neutral", "count": 9},
            {"theme_persistence_tag": "theme_fade_watch", "count": 2},
        ],
        "top_persistent_themes": [
            {
                "quant_theme_bucket": "semiconductor_tech",
                "theme_name_kr": "IT/반도체·기술",
                "theme_ret_1w": 0.169276,
                "theme_ret_1m": 0.702986,
                "theme_momentum_score": 2.18963,
                "theme_rotation_score": 1.709684,
                "leading_theme_rank": 1,
                "mapping_confidence": 0.92,
                "theme_continue_prob": 0.866301,
                "theme_fade_prob": 0.108232,
                "theme_persistence_score": 0.758069,
                "theme_persistence_tag": "theme_persist_strong",
            }
        ],
        "top_fade_risk_themes": [
            {
                "quant_theme_bucket": "energy_utility_infra",
                "theme_name_kr": "에너지·화학",
                "theme_ret_1w": 0.124835,
                "theme_ret_1m": 0.373754,
                "theme_momentum_score": 0.599201,
                "theme_rotation_score": 1.048244,
                "leading_theme_rank": 4,
                "mapping_confidence": 0.66,
                "theme_continue_prob": 0.380721,
                "theme_fade_prob": 0.495613,
                "theme_persistence_score": -0.114892,
                "theme_persistence_tag": "theme_fade_watch",
            }
        ],
    }
    etf_shadow_portfolio_payload = {
        "source_name": "etf_ai_shadow_portfolio_current",
        "schema_version": "1.0",
        "visibility": "admin_only",
        "model_code": "AI-ETF-SHADOW-PORTFOLIO-V01",
        "model_name_ko": "ETF전용포트폴리오AI",
        "model_role": "admin_only_shadow_observation",
        "status": "shadow_observation",
        "as_of_date": "2026-05-08",
        "generated_at": "2026-05-11T21:53:10",
        "component_models": [
            {
                "model_code": "AI-ETF-ROLE-ALLOCATION-V01",
                "model_name_ko": "ETF역할배분AI",
                "role": "role_selection",
                "quality_gate": "no_watch_plus",
                "evaluation": {
                    "auc": 0.605467,
                    "train_rows": 384,
                    "valid_rows": 132,
                    "current_signal_date": "2026-05-08",
                },
            },
            {
                "model_code": "AI-ETF-ROLE-WEIGHT-TEMPLATE-V01",
                "model_name_ko": "ETF비중템플릿AI",
                "role": "role_weight_template_selection",
                "quality_gate": "aum_p20",
                "evaluation": {
                    "auc": 0.910138,
                    "train_rows": 756,
                    "valid_rows": 243,
                    "current_signal_date": "2026-05-08",
                },
            },
        ],
        "current_decision": {
            "regime_mode": "neutral",
            "selected_role": "CORE_BETA",
            "selected_role_prob": 0.54337,
            "selected_template": "ON_THEME_TILT",
            "selected_template_prob": 0.376965,
            "mode_default_template": "NEUTRAL_BALANCED",
        },
        "backtest_summary": [
            {
                "variant": "template_ai_aum_p20_top1",
                "source_policy": "ai_top1_template",
                "observations": 27,
                "avg_1m_ret": 0.041287,
                "median_1m_ret": 0.010988,
                "win_rate": 0.62963,
                "avg_1m_mdd": -0.035597,
                "avg_1m_risk_adj": 0.023489,
                "compounded_validation_return": 1.630123,
            }
        ],
        "current_holdings": [
            {
                "variant": "template_ai_aum_p20_top1",
                "source": "template_ai",
                "signal_date": "2026-05-08T00:00:00.000",
                "regime_mode": "neutral",
                "role_key": "CORE_BETA",
                "role_weight": 1.0,
                "ticker": "069500",
                "name": "KODEX 200",
                "holding_weight": 0.33333333,
                "sleeve_selection_score": 1.327333,
                "sleeve_premium_discount": 0.002745,
                "sleeve_daily_tracking_gap_pct": 0.001333,
                "as_of_date": "2026-05-08",
            }
        ],
    }
    current_dir = current_path.parent
    extra_payloads = {
        "ai_learning_models_current.json": learning_payload,
        "ai_shadow_observation.json": candidate_validation_payload,
        "valuation_ai_shadow_monitor.json": valuation_monitor_payload,
        "downside_risk_ai_current.json": downside_current_payload,
        "downside_risk_ai_shadow_tracker.json": downside_tracker_payload,
        "theme_persistence_ai_current.json": theme_persistence_payload,
        "etf_ai_shadow_portfolio_current.json": etf_shadow_portfolio_payload,
    }
    for filename, payload in extra_payloads.items():
        current_dir.joinpath(filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    current_path.write_text(
        json.dumps(current_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    performance_path.write_text(
        json.dumps(performance_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def set_valuation_ai_env(monkeypatch, current_path: Path, performance_path: Path) -> None:
    current_dir = current_path.parent
    env_paths = {
        "VALUATION_AI_LEARNING_CURRENT_PATH": (current_dir / "ai_learning_models_current.json"),
        "VALUATION_AI_CANDIDATE_VALIDATION_PATH": (current_dir / "ai_shadow_observation.json"),
        "VALUATION_AI_VALUATION_CURRENT_PATH": current_path,
        "VALUATION_AI_VALUATION_PERFORMANCE_PATH": performance_path,
        "VALUATION_AI_VALUATION_MONITOR_PATH": (current_dir / "valuation_ai_shadow_monitor.json"),
        "VALUATION_AI_DOWNSIDE_CURRENT_PATH": (current_dir / "downside_risk_ai_current.json"),
        "VALUATION_AI_DOWNSIDE_TRACKER_PATH": (
            current_dir / "downside_risk_ai_shadow_tracker.json"
        ),
        "VALUATION_AI_THEME_PERSISTENCE_PATH": (current_dir / "theme_persistence_ai_current.json"),
        "VALUATION_AI_ETF_SHADOW_PORTFOLIO_PATH": (
            current_dir / "etf_ai_shadow_portfolio_current.json"
        ),
    }
    for env_name, env_path in env_paths.items():
        monkeypatch.setenv(env_name, str(env_path))


def seed_tseries_discovery_for_internal_models(target_path: Path) -> None:
    payload = {
        "source_name": "handoff:tseries_discovery_current",
        "as_of_date": "2026-04-23",
        "generated_at": "2026-04-24T21:53:23",
        "models": [
            {
                "model_code": "T-STOCK-V01",
                "performance_summary": {
                    "performance_subject_type": "shadow_portfolio",
                    "headline_metrics": {
                        "cagr": 1.904405,
                        "mdd": -0.051462,
                        "sharpe": 3.205201,
                        "trailing_1m": 0.12,
                        "trailing_3m": 0.23,
                        "trailing_6m": 0.35,
                        "trailing_1y": 1.20,
                        "reference_full": 4.56,
                    },
                    "period_metrics": [
                        {
                            "period": "3M",
                            "cagr": 1.234,
                            "mdd": -0.05,
                            "sharpe": 2.91,
                            "total_return": 0.77,
                        }
                    ],
                },
            }
        ],
    }
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_tseries_discovery_for_new_entries(target_root: Path) -> None:
    target_path = (
        target_root / "tseries_discovery" / "current" / "quantservice_tseries_discovery.json"
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_name": "handoff:tseries_discovery_current",
        "as_of_date": "2026-04-14",
        "generated_at": "2026-04-14T23:08:39",
        "models": [
            {
                "model_code": "T-STOCK-V01",
                "asof_date": "2026-04-08",
                "rolling_watchlist": {
                    "items": [
                        {
                            "ticker": "022100",
                            "name": "포스코DX",
                            "watch_status": "new",
                            "appearances_recent": 1,
                            "is_current": True,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "watch_status": "new",
                            "appearances_recent": 3,
                            "is_current": True,
                            "prev_seen_asof": "2026-03-25",
                        },
                    ]
                },
            },
            {
                "model_code": "T-ETF-V01",
                "asof_date": "2026-03-25",
                "rolling_watchlist": {"items": []},
            },
        ],
    }
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_admin_new_entries_page_requires_admin_and_renders_user_scope(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/new-entries").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )
    response = client.get(
        "/admin/new-entries?scope=user&event_type=new_entry&period=4w&model=stable"
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "신규 편입 추적" in body
    assert "사용자용 모델 신규 편입" in body
    assert "삼성전자" in body
    assert "신규 편입" in body


def test_admin_new_entries_api_supports_internal_scope(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )

    response = client.get(
        "/api/v1/admin/new-entries?scope=internal&event_type=new_entry&period=all&model=S2"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["scope"] == "internal"
    assert payload["event_type"] == "new_entry"
    assert payload["rows"]
    assert payload["rows"][0]["model_code"] == "S2"
    assert payload["rows"][0]["ticker"] == "005930"
    assert payload["rows"][0]["is_current"] is False
    assert round(payload["rows"][0]["current_return"], 4) == 0.05
    assert round(payload["rows"][0]["forward_1m_mdd"], 6) == -0.051393
    assert round(payload["rows"][0]["forward_1m_sharpe"], 6) == 5.716243
    assert {row["ticker"] for row in payload["rows"]} == {"005930"}
    assert {row["security_code"] for row in payload["weekly_rankings"]} == {"005930"}


def test_admin_new_entries_api_supports_tseries_scope(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )
    response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=promotion&period=all&model=T-STOCK-V01"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["scope"] == "tseries"
    assert payload["event_type"] == "promotion"
    assert payload["rows"]
    assert payload["rows"][0]["model_code"] == "T-STOCK-V01"


def test_admin_new_entries_api_includes_weekly_rankings(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )
    response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=promotion&period=all&model=T-STOCK-V01"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["weekly_rankings_total_count"] == 1
    assert payload["weekly_rankings"]
    assert payload["weekly_rankings"][0]["rank_no"] == 2
    assert payload["weekly_rankings"][0]["score_basis"] == "stage_blend"


def test_admin_new_entries_api_supports_i_series_internal_model(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )
    response = client.get(
        "/api/v1/admin/new-entries"
        "?scope=internal&event_type=new_entry&period=all&model=I-STOCK-STRONG-RSI-V01"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["model"] == "I-STOCK-STRONG-RSI-V01"
    assert payload["rows"]
    assert payload["rows"][0]["score"] == 125.0
    assert payload["rows"][0]["score_basis"] == "i_raw_score"
    assert payload["rows"][0]["score_display_mode"] == "number"
    actual_live = payload["actual_live_performance"]
    assert actual_live["metric_basis"] == "actual_market_price_forward_return_since_live_start"
    assert actual_live["total_count"] == 4
    stable_live = next(row for row in actual_live["rows"] if row["model_code"] == "stable")
    assert stable_live["model_label"] == "안정형"
    one_month_metric = next(metric for metric in stable_live["metrics"] if metric["key"] == "1m")
    assert round(one_month_metric["mdd"], 6) == -0.051393
    assert round(one_month_metric["sharpe"], 6) == 5.716243
    assert one_month_metric["mdd_sample_count"] == 1
    assert one_month_metric["sharpe_sample_count"] == 1
    assert "6m" not in {metric["key"] for metric in stable_live["metrics"]}
    assert "1y" not in {metric["key"] for metric in stable_live["metrics"]}
    i_live = next(
        row for row in actual_live["rows"] if row["model_code"] == "I-STOCK-STRONG-RSI-V01"
    )
    assert i_live["scope"] == "internal"
    assert i_live["live_event_count"] == 0
    assert i_live["metrics"][0]["avg_return"] is None
    assert i_live["metrics"][0]["has_sample"] is False


def test_admin_new_entries_page_renders_weekly_rankings_table(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )
    response = client.get("/admin/new-entries?scope=tseries&event_type=promotion&period=all")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "주간 순위 히스토리" in body
    assert "점수 근거" in body
    assert "stage_blend" in body
    assert "모델별 실제 운영 성과" in body
    assert "운영 시작 이후 모델 편입 종목의 실제 시장가격 추적 결과" in body
    assert "1M MDD" in body
    assert "1M Sharpe" in body
    assert "-5.14%" in body
    assert "5.72" in body
    assert "N/A" in body


def test_admin_valuation_ai_requires_admin_and_renders_page(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    current_path = tmp_path / "valuation_ai_challenger_current.json"
    performance_path = tmp_path / "valuation_ai_challenger_shadow_performance.json"
    seed_valuation_ai_payloads(current_path, performance_path)
    set_valuation_ai_env(monkeypatch, current_path, performance_path)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/valuation-ai").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/valuation-ai",
        follow_redirects=True,
    )
    response = client.get("/admin/valuation-ai?scope=internal&risk_tag=caution")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "AI 학습 모델" in body
    assert "AI 학습 모델의 shadow 관찰용" in body
    assert "공통 지표 해석 가이드" in body
    assert "모델 해석 가이드" in body
    assert "Public 추천 미반영" in body
    assert "AI-CANDIDATE-VALIDATION-V01" in body
    assert "AI-GROWTH-VALUATION-V01" in body
    assert "AI-DOWNSIDE-RISK-V01" in body
    assert "AI-THEME-PERSISTENCE-V01" in body
    assert "AI-ETF-SHADOW-PORTFOLIO-V01" in body
    assert "퀀트후보검증AI" in body
    assert "하락위험예측AI" in body
    assert "테마지속성AI" in body
    assert "ETF전용포트폴리오AI" in body
    assert "ETF 전용 shadow 포트폴리오 관찰" in body
    assert "실제 추천이 아니라 시장국면별 ETF 배분 가능성을 관찰" in body
    assert "CORE_BETA" in body
    assert "template_ai_aum_p20_top1" in body
    assert "KODEX 200" in body
    assert "ETF역할배분AI" in body
    assert "label_theme_continue_1m" in body
    assert "theme_persist_strong" in body
    assert "IT/반도체·기술" in body
    assert "BASE" in body
    assert "QM_MARKET_THEME" in body
    assert "QM_MARKET_RISK" in body
    assert "제룡전기" in body
    assert "power_grid" in body
    assert "N/A" in body


def test_admin_valuation_ai_api_filters_candidates(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    current_path = tmp_path / "valuation_ai_challenger_current.json"
    performance_path = tmp_path / "valuation_ai_challenger_shadow_performance.json"
    seed_valuation_ai_payloads(current_path, performance_path)
    set_valuation_ai_env(monkeypatch, current_path, performance_path)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/valuation-ai",
        follow_redirects=True,
    )
    response = client.get("/api/v1/admin/valuation-ai?scope=internal&challenger_state=favorable")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["as_of_date"] == "2026-05-08"
    assert {row["model_code"] for row in payload["models"]} == {
        "AI-CANDIDATE-VALIDATION-V01",
        "AI-GROWTH-VALUATION-V01",
        "AI-DOWNSIDE-RISK-V01",
        "AI-CANDIDATE-RANK-DELTA-V01",
        "AI-THEME-PERSISTENCE-V01",
        "AI-ETF-SHADOW-PORTFOLIO-V01",
        "AI-ETF-ROLE-ALLOCATION-V01",
        "AI-ETF-ROLE-WEIGHT-TEMPLATE-V01",
    }
    assert "candidate_validation" in payload["details"]
    assert "downside_risk_ai" in payload["details"]
    assert "theme_persistence_ai" in payload["details"]
    assert "etf_shadow_portfolio_ai" in payload["details"]
    assert payload["details"]["theme_persistence_ai"]["feature_mode"] == "BASE"
    assert (
        payload["details"]["etf_shadow_portfolio_ai"]["current_decision"]["selected_role"]
        == "CORE_BETA"
    )
    assert (
        payload["details"]["etf_shadow_portfolio_ai"]["current_holdings"][0]["name"] == "KODEX 200"
    )
    assert payload["candidates"][0]["security_code"] == "033100"
    assert payload["candidates"][0]["risk_tag"] == "caution"
    assert payload["performance_summary"][0]["avg_sharpe"] is None
    assert payload["performance_detail"][0]["live_current_sharpe"] is None


def test_top_nav_shows_valuation_ai_only_for_admin(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    current_path = tmp_path / "valuation_ai_challenger_current.json"
    performance_path = tmp_path / "valuation_ai_challenger_shadow_performance.json"
    seed_valuation_ai_payloads(current_path, performance_path)
    set_valuation_ai_env(monkeypatch, current_path, performance_path)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")
    access_store.register_local_user(
        email="member@example.com",
        password="pass1234",
        phone_number="01012345678",
    )

    anonymous_client = app.test_client()
    assert "AI 학습 모델" not in anonymous_client.get("/").get_data(as_text=True)

    member_client = app.test_client()
    login_user(
        member_client,
        email="member@example.com",
        password="pass1234",
        follow_redirects=True,
    )
    assert "AI 학습 모델" not in member_client.get("/").get_data(as_text=True)
    assert member_client.get("/admin/valuation-ai").status_code == 404

    admin_client = app.test_client()
    login_user(
        admin_client,
        email="admin@example.com",
        password="pass1234",
        follow_redirects=True,
    )
    admin_body = admin_client.get("/").get_data(as_text=True)
    assert "AI 학습 모델" in admin_body
    assert admin_client.get("/admin/valuation-ai").status_code == 200


def test_admin_internal_models_requires_admin_and_renders_page(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    anonymous_client = app.test_client()
    assert anonymous_client.get("/admin/internal-models").status_code == 404

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/internal-models",
        follow_redirects=True,
    )
    response = client.get("/admin/internal-models")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "내부용 모델" in body
    assert "S2" in body
    assert "I-series Strong RSI" in body
    assert "강한 RSI와 초기 상승 탄력" in body
    assert "T-STOCK-V01" in body
    assert "internal-summary-metrics" in body
    assert "1Y SHARPE" in body
    assert "최신 기준" in body
    assert "품질과 균형을 함께 보며" in body
    assert "신규/재편입" in body
    assert "제외/탈락" in body
    assert "scope=" not in body
    assert "event rows" not in body
    assert "ranking rows" not in body


def test_admin_internal_models_api_returns_models(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/internal-models",
        follow_redirects=True,
    )
    response = client.get("/api/v1/admin/internal-models")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["as_of_date"] == "2026-04-14"
    model_codes = {row["model_code"] for row in payload["models"]}
    assert "S2" in model_codes
    assert "I-STOCK-STRONG-RSI-V01" in model_codes
    assert "T-STOCK-V01" in model_codes
    i_model = next(
        row for row in payload["models"] if row["model_code"] == "I-STOCK-STRONG-RSI-V01"
    )
    assert i_model["display_name"] == "I-series Strong RSI"
    assert round(i_model["performance"]["cagr_proxy"], 6) == 0.42
    assert round(i_model["performance"]["mdd"], 6) == -0.12
    assert round(i_model["performance"]["sharpe"], 6) == 1.8
    assert i_model["performance_basis"] == "i_series_shadow"
    assert i_model["holdings"][0]["rank_no"] == 1
    assert i_model["holdings"][0]["score"] == 125.0
    assert i_model["holdings"][0]["score_basis"] == "i_raw_score"
    assert i_model["holdings"][0]["score_display_mode"] == "number"
    assert i_model["holdings"][0]["universe_rank_no"] == 1
    assert i_model["holdings"][0]["display_score"] == 125.0
    assert [row["period"] for row in i_model["period_view"]["supporting"][:7]] == [
        "1W",
        "2W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "ITD",
    ]


def test_admin_internal_models_uses_tseries_discovery_performance_basis(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    seed_admin_new_entry_tracker_payload(tracker_path)
    tseries_path = tmp_path / "quantservice_tseries_discovery.json"
    seed_tseries_discovery_for_internal_models(tseries_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    monkeypatch.setenv("TSERIES_DISCOVERY_PATH", str(tseries_path))
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/internal-models",
        follow_redirects=True,
    )
    response = client.get("/api/v1/admin/internal-models")

    assert response.status_code == 200
    payload = response.get_json()
    model = next(row for row in payload["models"] if row["model_code"] == "T-STOCK-V01")
    assert round(model["performance"]["cagr_proxy"], 6) == 1.904405
    assert round(model["performance"]["mdd"], 6) == -0.051462
    assert round(model["performance"]["sharpe"], 6) == 3.205201
    assert model["performance_basis"] == "shadow_portfolio"


def test_admin_menu_shows_internal_models_link_for_admin(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(client, email="admin@example.com", password="pass1234", follow_redirects=True)
    response = client.get("/")

    assert response.status_code == 200
    assert "내부용 모델" in response.get_data(as_text=True)


def test_admin_new_entries_api_uses_tseries_rolling_watchlist_for_new_events(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_tseries_discovery_for_new_entries(tmp_path)
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tmp_path / "missing_tracker.json"))
    monkeypatch.setattr(
        "service_platform.web.admin_new_entries_api.DEFAULT_TRACKER_PATH",
        tmp_path / "missing_default_tracker.json",
    )
    monkeypatch.setattr(
        "service_platform.web.admin_new_entries_api.QUANT_TRACKER_PATH",
        tmp_path / "missing_quant_tracker.json",
    )
    remote_settings = replace(
        settings,
        snapshot_gcs_base_url=tmp_path.as_uri(),
    )
    app = create_app(remote_settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )

    new_response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=new_entry&period=all&model=T-STOCK-V01"
    )
    re_response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=re_entry&period=all&model=T-STOCK-V01"
    )
    both_response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=new_or_re_entry&period=all&model=T-STOCK-V01"
    )

    assert new_response.status_code == 200
    new_payload = new_response.get_json()
    assert new_payload["rows"]
    assert new_payload["rows"][0]["ticker"] == "022100"
    assert new_payload["rows"][0]["event_type"] == "new_entry"

    assert re_response.status_code == 200
    re_payload = re_response.get_json()
    assert re_payload["rows"]
    assert re_payload["rows"][0]["ticker"] == "000660"
    assert re_payload["rows"][0]["event_type"] == "re_entry"

    assert both_response.status_code == 200
    both_payload = both_response.get_json()
    tickers = {row["ticker"] for row in both_payload["rows"]}
    assert {"022100", "000660"}.issubset(tickers)


def test_admin_new_entries_api_prefers_tracker_over_tseries_rolling(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_tseries_discovery_for_new_entries(tmp_path)
    tracker_path = tmp_path / "admin_new_entry_tracker.json"
    tracker_payload = {
        "source_name": "handoff:admin_new_entry_tracker",
        "schema_version": "v1",
        "visibility": "admin_only",
        "as_of_date": "2026-04-17",
        "generated_at": "2026-04-18T19:19:04",
        "summary": {
            "user_models": [],
            "internal_models": [],
            "tseries_models": [
                {"model_code": "T-STOCK-V01", "event_type": "new_entry", "count": 1}
            ],
        },
        "user_models": [],
        "internal_models": [],
        "tseries_models": [
            {
                "scope": "tseries",
                "model_code": "T-STOCK-V01",
                "event_type": "new_entry",
                "event_date": "2026-04-17",
                "week_end": "2026-04-17",
                "security_code": "999999",
                "display_name": "테스트종목",
                "delta_weight": None,
                "curr_weight": None,
                "is_current": True,
                "forward_returns": {"1w": None, "2w": None, "1m": None, "3m": None},
                "current_return": None,
            }
        ],
    }
    tracker_path.write_text(
        json.dumps(tracker_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ADMIN_NEW_ENTRY_TRACKER_PATH", str(tracker_path))
    remote_settings = replace(
        settings,
        snapshot_gcs_base_url=tmp_path.as_uri(),
    )
    app = create_app(remote_settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.authenticate_or_register("admin@example.com", "pass1234")
    access_store.assign_role(email="admin@example.com")

    client = app.test_client()
    login_user(
        client,
        email="admin@example.com",
        password="pass1234",
        next_url="/admin/new-entries",
        follow_redirects=True,
    )

    response = client.get(
        "/api/v1/admin/new-entries?scope=tseries&event_type=new_entry&period=all&model=T-STOCK-V01"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_name"] == "handoff:admin_new_entry_tracker"
    assert payload["rows"]
    assert payload["rows"][0]["ticker"] == "999999"


def test_ops_viewer_email_receives_ops_and_admin_access_on_login(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="hrchoi@koreascf.com",
        password="pass1234",
        phone_number="01012345678",
    )
    client = app.test_client()
    login_user(
        client,
        email="hrchoi@koreascf.com",
        password="pass1234",
        next_url="/new-entries",
        follow_redirects=True,
    )

    user_response = client.get("/new-entries")
    discovery_page_response = client.get("/discovery")
    admin_response = client.get("/admin")

    assert user_response.status_code == 200
    assert discovery_page_response.status_code in {200, 503}
    assert admin_response.status_code == 200


def test_ops_viewer_can_access_investment_portfolio_page(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, trial_mode=False)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="hrchoi@koreascf.com",
        password="pass1234",
        phone_number="01012345678",
    )
    client = app.test_client()

    anonymous_response = client.get("/investment-portfolio")
    login_user(
        client,
        email="hrchoi@koreascf.com",
        password="pass1234",
        next_url="/investment-portfolio",
        follow_redirects=True,
    )
    page_response = client.get("/investment-portfolio")
    api_response = client.get("/api/v1/investment-portfolio")

    assert anonymous_response.status_code == 404
    assert page_response.status_code == 200
    assert "투자 포트폴리오" in page_response.get_data(as_text=True)
    assert "ETF 전략" in page_response.get_data(as_text=True)
    assert api_response.status_code == 200
    assert api_response.get_json()["page"] == "투자 포트폴리오"


def test_investment_portfolio_can_read_remote_current_json(tmp_path: Path) -> None:
    remote_dir = tmp_path / "remote" / "admin" / "current"
    remote_dir.mkdir(parents=True)
    payload_path = remote_dir / "investment_portfolio_latest.json"
    payload_path.write_text(
        json.dumps(
            {
                "as_of_date": "2026-05-22",
                "generated_at": "2026-05-23T14:35:53+09:00",
                "market_risk": {},
                "etf_strategy": {"selected_model": "E-ETF-V01"},
                "stock_strategy": {"candidates": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = replace(
        build_settings(tmp_path),
        snapshot_gcs_base_url=(tmp_path / "remote").as_uri(),
    )

    bundle = InvestmentPortfolioApi(
        primary_path=tmp_path / "missing-primary.json",
        fallback_path=tmp_path / "missing-fallback.json",
        db_path=tmp_path / "missing.db",
        settings=settings,
    ).load_bundle()

    assert bundle.source_path.endswith("/admin/current/investment_portfolio_latest.json")
    assert bundle.view["as_of_date"] == "2026-05-22"
    assert bundle.view["etf_strategy"]["selected_model"] == "E-ETF-V01"


def test_investment_portfolio_normalizes_weight_policy_and_selection_date(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "investment_portfolio_latest.json"
    payload_path.write_text(
        json.dumps(
            {
                "as_of_date": "2026-05-25",
                "generated_at": "2026-05-25T19:53:26+09:00",
                "market_risk": {
                    "rating": "Constructive Watch",
                    "step1_v2": {
                        "score": 63.0,
                        "display_rating": "4등급 중립 상단",
                        "effective_asof": "2026-05-22T18:00:00+09:00",
                        "legacy_rating": "Constructive Watch",
                        "is_boundary": True,
                        "boundary_reason": "경계 구간",
                        "axes": [
                            {
                                "axis": "시장 방향성",
                                "score": 18,
                                "max_score": 20,
                                "reasons": ["KOSPI 0.41%"],
                            }
                        ],
                    },
                },
                "etf_strategy": {
                    "portfolio_weight_policy": {
                        "logic_version": "portfolio_weight_policy_v1_20260528",
                        "stock_selection_policy": "상위 10개 유지",
                        "stock_weight_range_pct": "0~15",
                        "etf_policy": "S6_DEFENSIVE_V1 중심",
                        "cash_or_defensive_policy": "현금성/방어 ETF 높게 유지",
                        "adjustment_rule": "비중만 조절",
                    },
                },
                "stock_strategy": {
                    "candidates": [
                        {
                            "ticker": "005930",
                            "name": "삼성전자",
                            "portfolio_selection_date": "2026-05-28",
                            "model_selection_date": "2026-05-13",
                            "latest_selection_date": "2026-05-13",
                            "first_portfolio_selection_date": "2026-05-13",
                            "first_portfolio_selection_price": 71500,
                            "final_portfolio_selection_date": "2026-05-28",
                            "final_portfolio_selection_price": 74400,
                            "return_from_first_portfolio_selection_pct": 4.0559,
                            "live_quote": {
                                "price": 74400,
                                "foreign_net_억원": -120.5,
                                "institution_net_억원": 80.0,
                            },
                        }
                    ],
                },
                "final_portfolio_strategy": {
                    "step1_rating": "4등급 중립 상단",
                    "step1_score": 63.0,
                    "stock_weight_range_pct": "0~15",
                    "etf_policy": "S6_DEFENSIVE_V1 중심",
                    "cash_or_defensive_policy": "현금성/방어 ETF 높게 유지",
                    "weight_policy": {
                        "stock_selection_policy": "상위 10개 유지",
                        "adjustment_rule": "비중만 조절",
                    },
                    "conclusion": "상위 10개 종목을 유지한다.",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = InvestmentPortfolioApi(
        primary_path=payload_path,
        fallback_path=payload_path,
        db_path=tmp_path / "missing.db",
    ).load_bundle()

    assert bundle.view["market_risk"]["rating"] == "4등급 중립 상단"
    assert bundle.view["market_risk"]["step1_v2"]["axes"][0]["score_label"] == "18.0/20"
    assert bundle.view["etf_strategy"]["portfolio_weight_policy"] == {
        "logic_version": "portfolio_weight_policy_v1_20260528",
        "basis": "",
        "stock_selection_policy": "상위 10개 유지",
        "stock_weight_range_pct": "0~15%",
        "etf_policy": "S6_DEFENSIVE_V1 중심",
        "cash_or_defensive_policy": "현금성/방어 ETF 높게 유지",
        "adjustment_rule": "비중만 조절",
    }
    candidate = bundle.view["stock_strategy"]["candidates"][0]
    assert candidate["model_selection_date"] == "2026-05-13"
    assert candidate["first_portfolio_selection_date"] == "2026-05-13"
    assert candidate["first_portfolio_selection_price"] == "71,500"
    assert candidate["final_portfolio_selection_date"] == "2026-05-28"
    assert candidate["final_portfolio_selection_price"] == "74,400"
    assert candidate["return_from_first_portfolio_selection_pct"] == "+4.06%"
    assert candidate["flow_status"] == "혼합/순매도"
    assert candidate["net_flow"] == "-40.5"
    assert candidate["foreign_net"] == "-120.5"
    assert candidate["institution_net"] == "80.0"
    assert "scenario_a" not in candidate
    assert "scenario_b" not in candidate
    assert bundle.view["final_portfolio_strategy"]["stock_weight_range_pct"] == "0~15%"
    assert bundle.view["final_portfolio_strategy"]["etf_policy"] == "S6_DEFENSIVE_V1 중심"
    assert (
        bundle.view["final_portfolio_strategy"]["cash_or_defensive_policy"]
        == "현금성/방어 ETF 높게 유지"
    )


def test_investment_portfolio_prefers_stock_candidate_model_display_from_latest_db(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "analysis.db"
    payload_path = tmp_path / "investment_portfolio_latest.json"
    payload_path.write_text(
        json.dumps(
            {
                "as_of_date": "2026-05-19",
                "generated_at": "2026-05-19T10:00:00",
                "market_risk": {},
                "etf_strategy": {},
                "stock_strategy": {
                    "candidates": [
                        {
                            "ticker": "005380",
                            "name": "현대차",
                            "model_groups": ["I", "S"],
                            "group": "core_candidate",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE portfolio_runs (
                run_id INTEGER PRIMARY KEY,
                live_data_status TEXT,
                live_data_source TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE portfolio_stock_candidates (
                run_id INTEGER,
                ticker TEXT,
                model_display TEXT,
                model_display_codes TEXT,
                model_ids TEXT,
                model_groups TEXT,
                live_price REAL,
                live_change_pct REAL,
                foreign_net_억원 REAL,
                institution_net_억원 REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE portfolio_stock_live_refresh_runs (
                refresh_id INTEGER PRIMARY KEY,
                status TEXT,
                source TEXT,
                fetched_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE v_portfolio_stock_live_latest (
                ticker TEXT,
                model_display TEXT,
                live_price REAL,
                live_change_pct REAL,
                foreign_net_억원 REAL,
                institution_net_억원 REAL,
                fetched_at TEXT,
                source TEXT
            )
            """
        )
        connection.execute("INSERT INTO portfolio_runs (run_id) VALUES (1)")
        connection.execute(
            """
            INSERT INTO portfolio_runs (run_id, live_data_status, live_data_source)
            VALUES (?, ?, ?)
            """,
            (2, "ok", "kiwoom_rest_ka10001+ka10059"),
        )
        connection.execute(
            """
            INSERT INTO portfolio_stock_candidates (
                run_id, ticker, model_display, model_display_codes, model_ids, model_groups,
                live_price, live_change_pct, foreign_net_억원, institution_net_억원
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "005380", "S", "S", "S2", "S", None, None, None, None),
        )
        connection.execute(
            """
            INSERT INTO portfolio_stock_candidates (
                run_id, ticker, model_display, model_display_codes, model_ids, model_groups,
                live_price, live_change_pct, foreign_net_억원, institution_net_억원
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                "005380",
                "I-STOCK / S2 / S2_PIT",
                "I-STOCK,S2,S2_PIT",
                "I-STOCK-STRONG-RSI-V01,S2,S2_PIT_V01",
                "I,S",
                604000,
                -8.9,
                -3882.7,
                -1248.7,
            ),
        )
        connection.execute(
            """
            INSERT INTO portfolio_stock_live_refresh_runs (
                refresh_id, status, source, fetched_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (1, "ok", "kiwoom_intraday_refresh", "2026-05-21T14:58:38+09:00"),
        )
        connection.execute(
            """
            INSERT INTO v_portfolio_stock_live_latest (
                ticker, model_display, live_price, live_change_pct,
                foreign_net_억원, institution_net_억원, fetched_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "005380",
                "I-STOCK / S2",
                667000,
                12.67,
                390.9,
                300.6,
                "2026-05-21T14:58:38+09:00",
                "kiwoom_rest_ka10001+kiwoom_rest_ka10059",
            ),
        )

    bundle = InvestmentPortfolioApi(
        primary_path=payload_path,
        fallback_path=payload_path,
        db_path=db_path,
    ).load_bundle()

    candidate = bundle.view["stock_strategy"]["candidates"][0]
    assert candidate["model_names"] == "I-STOCK / S2"
    assert candidate["price"] == "667,000"
    assert candidate["change_pct"] == "+12.67%"
    assert candidate["foreign_net"] == "390.9"
    assert candidate["institution_net"] == "300.6"
    assert bundle.view["stock_strategy"]["live_status"] == "ok"
    assert bundle.view["stock_strategy"]["live_source"] == "kiwoom_intraday_refresh"
    assert bundle.view["stock_strategy"]["live_fetched_at"] == "2026-05-21T14:58:38+09:00"


def test_user_snapshot_can_read_remote_current_json(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    remote_settings = replace(
        settings,
        snapshot_source="remote",
        snapshot_gcs_base_url=settings.user_snapshot_dir.as_uri(),
    )
    app = create_app(remote_settings)
    client = app.test_client()

    home_response = client.get("/")
    today_response = client.get("/api/v1/model-snapshots/today")
    performance_response = client.get("/performance")
    changes_response = client.get("/changes")
    status_snapshot = app.config["USER_SNAPSHOT_API"].get_status(force_refresh=True)

    assert home_response.status_code == 200
    assert today_response.status_code == 200
    assert performance_response.status_code == 404
    assert changes_response.status_code == 200
    assert today_response.get_json()["as_of_date"] == "2026-03-20"
    assert status_snapshot.source_name == "snapshot-remote"
    assert status_snapshot.as_of_date == "2026-03-20"


def test_changes_page_renders_collapsible_change_history(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    app = create_app(settings)
    client = app.test_client()

    page_response = client.get("/changes")
    history_response = client.get("/api/v1/changes/history")

    assert page_response.status_code == 200
    body = page_response.get_data(as_text=True)
    assert "주간 변경내역" in body
    assert "change-history-item" in body
    assert "2026-03-20" in body
    assert history_response.status_code == 200
    history_payload = history_response.get_json()
    assert history_payload["source"] == "recent_changes_fallback"
    assert history_payload["history"][0]["change_date"] == "2026-03-20"
    assert len(history_payload["history"][0]["changes"]) == 2


def test_user_snapshot_can_read_optional_change_history_payload(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    history_payload = {
        "as_of_date": "2026-03-20",
        "history": [
            {
                "change_date": "2026-03-13",
                "summary": "직전 주 공개 모델 변경내역",
                "changes": [
                    {
                        "user_model_name": "안정형",
                        "quant_model_name": "안정형 퀀트투자 모델",
                        "change_type": "rebalanced",
                        "summary": "안정형 비중을 조정했습니다.",
                        "increase_items": [
                            {
                                "display_name": "삼성전자",
                                "security_code": "005930",
                                "delta_weight": 0.01,
                                "direction": "increase",
                            }
                        ],
                        "decrease_items": [],
                        "reason_text": "방어 자산과 주식 비중을 조정했습니다.",
                    }
                ],
            }
        ],
    }
    (settings.user_snapshot_dir / "user_model_change_history.json").write_text(
        json.dumps(history_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/api/v1/changes/history")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["history"][0]["change_date"] == "2026-03-13"
    assert payload["history"][0]["changes"][0]["service_profile"] == "stable"


def test_changes_history_supports_weekly_monthly_payload_and_filters(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    recent_path = settings.user_snapshot_dir / "user_recent_changes.json"
    recent_payload = json.loads(recent_path.read_text(encoding="utf-8-sig"))
    recent_payload["changes"] = []
    recent_path.write_text(
        json.dumps(recent_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    history_payload = {
        "source_name": "quant:user_model_change_history",
        "schema_version": "1.0",
        "as_of_date": "2026-04-10",
        "generated_at": "2026-04-10T20:49:24",
        "profiles": ["stable", "balanced", "growth"],
        "available_dates": ["2026-04-10", "2026-04-03"],
        "weekly": [
            {
                "period_type": "weekly",
                "period_key": "2026-04-10",
                "as_of_date": "2026-04-10",
                "models": [
                    {
                        "user_model_name": "안정형",
                        "service_profile": "stable",
                        "change_type": "rebalanced",
                        "summary": "안정형 비중을 조정했습니다.",
                        "increase_items": [
                            {
                                "display_name": "삼성전자",
                                "security_code": "005930",
                                "delta_weight": 0.01,
                                "direction": "increase",
                            }
                        ],
                        "decrease_items": [],
                        "reason_text": "공개 모델 기준 비중을 조정했습니다.",
                    },
                    {
                        "user_model_name": "성장형",
                        "service_profile": "growth",
                        "change_type": "rebalanced",
                        "summary": "성장형 비중을 조정했습니다.",
                        "increase_items": [],
                        "decrease_items": [
                            {
                                "display_name": "현금/대기자금",
                                "security_code": None,
                                "delta_weight": -0.01,
                                "direction": "decrease",
                            }
                        ],
                        "reason_text": "공개 모델 기준 비중을 조정했습니다.",
                    },
                ],
            }
        ],
        "monthly": [
            {
                "period_type": "monthly",
                "period_key": "2026-04",
                "start_date": "2026-04-01",
                "end_date": "2026-04-10",
                "source_dates": ["2026-04-10", "2026-04-03"],
                "models": [
                    {
                        "user_model_name": "성장형",
                        "service_profile": "growth",
                        "change_type": "aggregate",
                        "summary": "성장형 월간 변경 집계입니다.",
                        "increase_items": [
                            {
                                "display_name": "SK하이닉스",
                                "security_code": "000660",
                                "direction": "increase",
                                "latest_delta_weight": 0.02,
                                "source_dates": ["2026-04-10"],
                                "occurrence_count": 1,
                            }
                        ],
                        "decrease_items": [],
                        "reason_text": "공개 모델 기준 월간 비중 변화를 집계했습니다.",
                    }
                ],
            }
        ],
    }
    (settings.user_snapshot_dir / "user_model_change_history.json").write_text(
        json.dumps(history_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    app = create_app(settings)
    client = app.test_client()

    recent_response = client.get("/api/v1/changes/recent")
    monthly_response = client.get("/api/v1/changes/history?period=monthly&model=growth")
    page_response = client.get("/changes?period=monthly&model=growth")

    assert recent_response.status_code == 200
    assert len(recent_response.get_json()["changes"]) == 2
    assert monthly_response.status_code == 200
    monthly_payload = monthly_response.get_json()
    assert monthly_payload["selected_period"] == "monthly"
    assert monthly_payload["items"][0]["models"][0]["service_profile"] == "growth"
    assert page_response.status_code == 200
    body = page_response.get_data(as_text=True)
    assert "월간 변경내역" in body
    assert "2026-04" in body
    assert "1회 관찰" in body


def test_user_snapshot_remote_current_accepts_publish_manifest_user_filename(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    remote_dir = tmp_path / "remote_user_current"
    seed_user_snapshot(remote_dir)
    (remote_dir / "publish_manifest.json").replace(remote_dir / "publish_manifest_user.json")
    remote_settings = replace(
        settings,
        snapshot_source="remote",
        snapshot_gcs_base_url=remote_dir.as_uri(),
    )
    app = create_app(remote_settings)
    client = app.test_client()

    manifest_response = client.get("/api/v1/manifest")
    status_snapshot = app.config["USER_SNAPSHOT_API"].get_status(force_refresh=True)

    assert manifest_response.status_code == 200
    assert manifest_response.get_json()["channel"] == "user-facing"
    assert status_snapshot.source_name == "snapshot-remote"


def test_user_snapshot_remote_current_falls_back_to_local_when_remote_is_out_of_sync(
    tmp_path: Path,
) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    remote_dir = tmp_path / "remote_user_current"
    seed_user_snapshot(remote_dir)

    recent_changes_path = remote_dir / "user_recent_changes.json"
    recent_changes_payload = json.loads(recent_changes_path.read_text(encoding="utf-8-sig"))
    recent_changes_payload["as_of_date"] = "2026-03-19"
    recent_changes_path.write_text(
        json.dumps(recent_changes_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )

    remote_settings = replace(
        settings,
        snapshot_source="remote",
        snapshot_gcs_base_url=remote_dir.as_uri(),
    )
    app = create_app(remote_settings)
    client = app.test_client()

    today_response = client.get("/api/v1/model-snapshots/today")
    status_snapshot = app.config["USER_SNAPSHOT_API"].get_status(force_refresh=True)

    assert today_response.status_code == 200
    assert today_response.get_json()["as_of_date"] == "2026-03-20"
    assert status_snapshot.source_name == "snapshot-local"
    assert (
        "원격 사용자 스냅샷을 읽지 못해 로컬 current 데이터를 사용합니다."
        in status_snapshot.warnings
    )
    assert any("기준일이 서로 다릅니다" in error for error in status_snapshot.errors)


def test_cardnews_files_are_internal_only(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    index_response = client.get("/cardnews/2026-04-29-brain-health/")
    static_image_response = client.get(
        "/static/cardnews/2026-04-29-brain-health/redbot_brain_health_01.png"
    )

    assert index_response.status_code == 404
    assert static_image_response.status_code == 404
