import json
from pathlib import Path

from service_platform.web.app import create_app
from service_platform.web.tseries_api import TSeriesOperationalApi
from tests.test_web.test_health import (
    build_settings,
    login_user,
    seed_market_analysis_snapshot,
    seed_trading_sign_snapshot,
    seed_user_snapshot,
)


def seed_tseries_discovery_payload(public_data_dir: Path) -> None:
    target_dir = public_data_dir / "tseries_discovery" / "current"
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_name": "handoff:tseries_discovery",
        "warnings": [],
        "errors": [],
        "models": [
            {
                "model_code": "T-STOCK-V01",
                "asof_date": "2026-03-26",
                "meta": {
                    "display_name": "전이형 발굴 모델 · 주식",
                    "version": "V01",
                    "asset_scope": "stock",
                },
                "profile": {
                    "profile_code": "operating_v2",
                    "threshold_values": {
                        "stage1_threshold": 0.52,
                        "stage2_confirmed_threshold": 0.525,
                        "stage2_near_threshold": 0.52,
                    },
                    "risk_filter_version": "stock_risk_filter_v1",
                },
                "run": {
                    "refresh_kind": "shadow_refresh",
                    "status": "success",
                    "finished_at": "2026-04-01 00:01:00",
                },
                "bucket_counts": {"confirmed": 6, "near": 3, "observe": 1},
                "top_by_bucket": {
                    "confirmed": [
                        {
                            "ticker": "047040",
                            "name": "대우건설",
                            "market": "KOSPI",
                            "theme_bucket": "construction_materials",
                            "theme_name_kr": "건설/소재",
                            "stage1_prob": 0.5225,
                            "stage2_prob": 0.5433,
                            "is_s2_overlap": False,
                        },
                        {
                            "ticker": "420770",
                            "name": "기가비스",
                            "market": "KOSDAQ",
                            "theme_bucket": "semiconductor_tech",
                            "theme_name_kr": "반도체/전자부품",
                            "stage1_prob": 0.5224,
                            "stage2_prob": 0.5403,
                            "is_s2_overlap": False,
                        },
                        {
                            "ticker": "000660",
                            "name": "SK하이닉스",
                            "market": "KOSPI",
                            "theme_bucket": "semiconductor_tech",
                            "theme_name_kr": "반도체/전자부품",
                            "stage1_prob": 0.5218,
                            "stage2_prob": 0.5381,
                            "is_s2_overlap": True,
                        },
                    ],
                    "near": [
                        {
                            "ticker": "096770",
                            "name": "SK이노베이션",
                            "market": "KOSPI",
                            "theme_bucket": "energy",
                            "theme_name_kr": "에너지",
                            "stage1_prob": 0.5198,
                            "stage2_prob": 0.5240,
                            "is_s2_overlap": False,
                        }
                    ],
                    "observe": [
                        {
                            "ticker": "035420",
                            "name": "NAVER",
                            "market": "KOSPI",
                            "theme_bucket": "platform",
                            "theme_name_kr": "플랫폼",
                            "stage1_prob": 0.5110,
                            "stage2_prob": 0.5170,
                            "is_s2_overlap": False,
                        }
                    ],
                },
                "shadow_summary": {
                    "confirmed": {
                        "obs_n": 1946,
                        "t10_hit_rate": 70.7,
                        "t3_hit_rate": 21.8,
                        "avg_stage1_prob": 0.522,
                        "avg_stage2_prob": 0.539,
                    },
                    "near": {
                        "obs_n": 536,
                        "t10_hit_rate": 71.1,
                        "t3_hit_rate": 17.7,
                        "avg_stage1_prob": 0.519,
                        "avg_stage2_prob": 0.523,
                    },
                },
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "display_metric": "cagr",
                        "cagr": 1.234,
                        "total_return": 1.876,
                        "mdd": -0.123,
                        "sharpe": 1.98,
                        "last_realized_date": "2025-11-26",
                    },
                    "period_metrics": [
                        {
                            "period": "3M",
                            "start_date": "2025-08-20",
                            "end_date": "2025-11-26",
                            "total_return": 0.25,
                            "cagr": 1.1,
                            "mdd": -0.05,
                            "sharpe": 2.4,
                        },
                        {
                            "period": "5Y",
                            "start_date": "2020-11-26",
                            "end_date": "2025-11-26",
                            "total_return": 0.88,
                            "cagr": 0.13,
                            "mdd": -0.21,
                            "sharpe": 0.91,
                        },
                        {
                            "period": "FULL",
                            "start_date": "2018-01-02",
                            "end_date": "2025-11-26",
                            "total_return": 1.25,
                            "cagr": 0.15,
                            "mdd": -0.24,
                            "sharpe": 0.96,
                        },
                    ],
                    "performance_subject_name": "T-series stock discovery basket",
                    "performance_subject_type": "shadow_portfolio",
                    "portfolio_generation_basis": (
                        "Equal-weight basket of confirmed and near candidates"
                    ),
                },
                "rolling_watchlist": {
                    "summary": [
                        {"bucket": "new", "count": 1},
                        {"bucket": "active", "count": 0},
                        {"bucket": "cooling", "count": 10},
                        {"bucket": "tier_core", "count": 4},
                    ],
                    "items": [
                        {
                            "ticker": "047040",
                            "name": "대우건설",
                            "market": "KOSPI",
                            "theme_bucket": "construction_materials",
                            "theme_name_kr": "건설/소재",
                            "watch_status": "new",
                            "watch_tier": "core",
                            "is_current": True,
                            "current_bucket": "confirmed",
                            "last_seen_asof": "2026-03-26",
                            "prev_seen_asof": "2026-03-19",
                            "appearances_recent": 2,
                            "consecutive_current": 1,
                            "stage1_prob": 0.5225,
                            "stage2_prob": 0.5433,
                        },
                        {
                            "ticker": "035420",
                            "name": "NAVER",
                            "market": "KOSPI",
                            "theme_bucket": "platform",
                            "theme_name_kr": "플랫폼",
                            "watch_status": "cooling",
                            "watch_tier": "monitor",
                            "is_current": False,
                            "current_bucket": None,
                            "last_seen_asof": "2026-03-19",
                            "prev_seen_asof": "2026-03-12",
                            "weeks_seen": 3,
                            "stage1_prob": 0.5110,
                            "stage2_prob": 0.5170,
                        },
                    ],
                },
            },
            {
                "model_code": "T-ETF-V01",
                "asof_date": "2026-03-31",
                "meta": {
                    "display_name": "전이형 발굴 모델 · ETF",
                    "version": "V01",
                    "asset_scope": "etf",
                },
                "profile": {
                    "profile_code": "operational_v1",
                    "threshold_summary": "임계값 미공개",
                    "risk_filter_version": "etf_risk_filter_v1",
                },
                "run": {
                    "refresh_kind": "shadow_refresh",
                    "status": "success",
                    "finished_at": "2026-04-01 00:01:00",
                },
                "bucket_counts": {"confirmed": 1, "near": 2, "observe": 0},
                "top_by_bucket": {
                    "confirmed": [
                        {
                            "ticker": "360750",
                            "name": "TIGER 미국S&P500",
                            "market": "ETF",
                            "theme_bucket": "us_equity",
                            "theme_name_kr": "미국주식",
                            "role_key": "CORE_BETA",
                            "role_confidence": 0.92,
                            "role_reason": "대표 미국 주식 지수 노출 ETF입니다.",
                            "stage1_prob": 0.6310,
                            "stage2_prob": 0.5510,
                        }
                    ],
                    "near": [
                        {
                            "ticker": "102110",
                            "name": "TIGER 200",
                            "market": "ETF",
                            "theme_bucket": "korea_equity",
                            "theme_name_kr": "국내주식",
                            "role_key": "STYLE_FACTOR",
                            "role_confidence": 0.81,
                            "role_reason": "국내 대표지수 추종 성격입니다.",
                            "stage1_prob": 0.6240,
                            "stage2_prob": 0.5410,
                        }
                    ],
                    "observe": [],
                },
                "shadow_summary": {
                    "confirmed": {
                        "obs_n": 69,
                        "t10_hit_rate": 17.4,
                        "t3_hit_rate": 8.7,
                        "avg_stage1_prob": 0.626,
                        "avg_stage2_prob": 0.551,
                    }
                },
                "performance_summary": {
                    "headline_metrics": {
                        "primary_period": "1Y",
                        "display_metric": "cagr",
                        "cagr": 0.321,
                        "total_return": 0.321,
                        "mdd": -0.044,
                        "sharpe": 2.25,
                        "last_realized_date": "2026-03-31",
                    },
                    "period_metrics": [
                        {
                            "period": "6M",
                            "start_date": "2025-09-30",
                            "end_date": "2026-03-31",
                            "total_return": 0.208,
                            "cagr": 0.461,
                            "mdd": -0.011,
                            "sharpe": 4.03,
                        },
                        {
                            "period": "5Y",
                            "start_date": "2021-03-31",
                            "end_date": "2026-03-31",
                            "total_return": 0.55,
                            "cagr": 0.09,
                            "mdd": -0.08,
                            "sharpe": 1.41,
                        },
                        {
                            "period": "FULL",
                            "start_date": "2019-01-02",
                            "end_date": "2026-03-31",
                            "total_return": 0.67,
                            "cagr": 0.08,
                            "mdd": -0.11,
                            "sharpe": 1.22,
                        },
                    ],
                    "performance_subject_name": "T-series ETF discovery basket",
                    "performance_subject_type": "shadow_portfolio",
                    "portfolio_generation_basis": (
                        "Equal-weight basket of confirmed and near candidates"
                    ),
                },
                "rolling_watchlist": {
                    "summary": [
                        {"bucket": "new", "count": 2},
                        {"bucket": "active", "count": 0},
                        {"bucket": "cooling", "count": 0},
                    ],
                    "items": [
                        {
                            "ticker": "360750",
                            "name": "TIGER 미국S&P500",
                            "market": "ETF",
                            "theme_bucket": "us_equity",
                            "theme_name_kr": "미국주식",
                            "role_key": "CORE_BETA",
                            "role_confidence": 0.92,
                            "role_reason": "대표 미국 주식 지수 노출 ETF입니다.",
                            "watch_status": "new",
                            "watch_tier": "core",
                            "is_current": True,
                            "current_bucket": "confirmed",
                            "last_seen_date": "2026-03-31",
                            "months_seen": 1,
                            "stage1_prob": 0.6310,
                            "stage2_prob": 0.5510,
                        },
                        {
                            "ticker": "102110",
                            "name": "TIGER 200",
                            "market": "ETF",
                            "theme_bucket": "korea_equity",
                            "theme_name_kr": "국내주식",
                            "role_key": "STYLE_FACTOR",
                            "role_confidence": 0.81,
                            "role_reason": "국내 대표지수 추종 성격입니다.",
                            "watch_status": "new",
                            "watch_tier": "monitor",
                            "is_current": True,
                            "current_bucket": "near",
                            "last_seen_date": "2026-03-31",
                            "months_seen": 1,
                            "stage1_prob": 0.6240,
                            "stage2_prob": 0.5410,
                        },
                    ],
                },
            },
        ],
    }
    (target_dir / "quantservice_tseries_discovery.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def seed_tseries_discovery_trading_sign_payload(public_data_dir: Path) -> None:
    target_dir = public_data_dir / "trading_sign" / "current"
    seed_trading_sign_snapshot(target_dir)

    detail_path = target_dir / "tradingsign_model_detail.json"
    overview_path = target_dir / "tradingsign_overview.json"
    detail = json.loads(detail_path.read_text(encoding="utf-8-sig"))
    overview = json.loads(overview_path.read_text(encoding="utf-8-sig"))

    t_models = [
        {
            "model_code": "T_STOCK_DISCOVERY",
            "model_name": "T-series 주식 발굴 신호",
            "signal_date": "2026-04-02",
            "record_count": 2,
            "state_counts": {"매수": 1, "보유": 0, "주의": 1, "매도": 0, "매수 대기": 0},
            "ui_block": {
                "title": "매매 신호(전일 종가 기준)",
                "description": ("이 신호는 전일 종가 기준으로 계산된 참고용 일간 점검 정보입니다."),
                "disclaimer": (
                    "이 상태는 공개 규칙 기반 모델의 참고용 해석이며 특정 이용자에 대한 "
                    "개별 매매 지시가 아닙니다."
                ),
                "signal_date": "2026-04-02",
                "data_asof_date": "2026-04-01",
                "generated_at": "2026-04-02T13:21:50",
                "profile_code": "T_STOCK_DISCOVERY",
                "state_chips": [
                    {"state": "매수", "count": 1},
                    {"state": "보유", "count": 0},
                    {"state": "주의", "count": 1},
                    {"state": "매도", "count": 0},
                    {"state": "매수 대기", "count": 0},
                ],
                "sections": [
                    {
                        "section_key": "recommended",
                        "title": "추천 종목 신호",
                        "record_count": 2,
                        "signals": [
                            {
                                "ticker": "047040",
                                "security_name": "대우건설",
                                "current_state": "매수",
                                "reason_summary": (
                                    "전일 종가 기준으로 신규 진입 조건을 충족했습니다."
                                ),
                                "latest_state_change_date": "2026-04-02",
                            },
                            {
                                "ticker": "035420",
                                "security_name": "NAVER",
                                "current_state": "주의",
                                "reason_summary": "추세 확인이 더 필요한 경고 상태입니다.",
                                "latest_state_change_date": "2026-04-01",
                            },
                        ],
                    },
                    {
                        "section_key": "held",
                        "title": "보유 종목 신호",
                        "record_count": 0,
                        "signals": [],
                    },
                ],
            },
        },
        {
            "model_code": "T_ETF_DISCOVERY",
            "model_name": "T-series ETF 발굴 신호",
            "signal_date": "2026-04-02",
            "record_count": 1,
            "state_counts": {"매수": 0, "보유": 1, "주의": 0, "매도": 0, "매수 대기": 0},
            "ui_block": {
                "title": "매매 신호(전일 종가 기준)",
                "description": ("이 신호는 전일 종가 기준으로 계산된 참고용 일간 점검 정보입니다."),
                "disclaimer": (
                    "이 상태는 공개 규칙 기반 모델의 참고용 해석이며 특정 이용자에 대한 "
                    "개별 매매 지시가 아닙니다."
                ),
                "signal_date": "2026-04-02",
                "data_asof_date": "2026-04-01",
                "generated_at": "2026-04-02T13:21:50",
                "profile_code": "T_ETF_DISCOVERY",
                "state_chips": [
                    {"state": "매수", "count": 0},
                    {"state": "보유", "count": 1},
                    {"state": "주의", "count": 0},
                    {"state": "매도", "count": 0},
                    {"state": "매수 대기", "count": 0},
                ],
                "sections": [
                    {
                        "section_key": "recommended",
                        "title": "추천 종목 신호",
                        "record_count": 1,
                        "signals": [
                            {
                                "ticker": "360750",
                                "security_name": "TIGER 미국S&P500",
                                "current_state": "보유",
                                "reason_summary": (
                                    "중장기 추세가 유지돼 보유 기준을 충족하고 있습니다."
                                ),
                                "latest_state_change_date": "2026-04-02",
                            }
                        ],
                    }
                ],
            },
        },
    ]

    detail["models"].extend(t_models)
    overview["models"].extend(
        {
            "model_code": model["model_code"],
            "model_name": model["model_name"],
            "signal_date": model["signal_date"],
            "record_count": model["record_count"],
            "state_counts": model["state_counts"],
        }
        for model in t_models
    )
    overview["summary"]["model_count"] = len(overview["models"])
    overview["summary"]["signal_count"] = sum(
        int(model.get("record_count") or 0) for model in overview["models"]
    )

    detail_path.write_text(
        json.dumps(detail, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )
    overview_path.write_text(
        json.dumps(overview, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8-sig",
    )


def login_ops_viewer(client, app) -> None:
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="hrchoi@koreascf.com",
        password="pass1234",
        phone_number="01012345678",
    )
    login_user(
        client,
        email="hrchoi@koreascf.com",
        password="pass1234",
        next_url="/discovery",
        follow_redirects=True,
    )


def test_tseries_api_routes_return_normalized_payloads(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    list_response = client.get("/api/v1/discovery/t-series")
    stock_response = client.get("/api/v1/discovery/t-series/T-STOCK-V01")
    etf_alias_response = client.get("/api/v1/discovery/t-series/T_ETF_DISCOVERY")

    assert list_response.status_code == 200
    models = list_response.get_json()["models"]
    assert [row["model_code"] for row in models] == ["T-STOCK-V01", "T-ETF-V01"]
    assert models[0]["latest_asof_date"] == "2026-03-26"
    assert models[0]["threshold_summary"] == "1단계 0.520 / 우선 후보 0.525 / 근접 후보 0.520"
    assert models[1]["bucket_counts"]["observe"] == 0

    assert stock_response.status_code == 200
    stock_payload = stock_response.get_json()
    assert stock_payload["meta"]["service_model_code"] == "T_STOCK_DISCOVERY"
    assert stock_payload["meta"]["display_name_ko"] == "전이형 발굴 모델"
    assert stock_payload["bucket_counts"] == {"confirmed": 6, "near": 3, "observe": 1}
    assert stock_payload["top_by_bucket"]["confirmed"][0]["ticker"] == "047040"
    assert stock_payload["top_by_bucket"]["confirmed"][2]["is_s2_overlap"] is True
    assert stock_payload["shadow_summary"]["confirmed"]["obs_n"] == 1946
    assert stock_payload["performance_summary"]["headline_metrics"]["primary_period"] == "1Y"
    assert stock_payload["performance_summary"]["portfolio_generation_basis"].startswith(
        "Equal-weight basket"
    )
    assert stock_payload["rolling_watchlist"]["enabled"] is True
    assert [row["status"] for row in stock_payload["rolling_watchlist"]["summary_rows"]] == [
        "new",
        "active",
        "cooling",
    ]
    assert stock_payload["rolling_watchlist"]["summary_rows"][2]["count"] == 10
    assert stock_payload["rolling_watchlist"]["items"][0]["watch_status"] == "new"
    assert stock_payload["rolling_watchlist"]["items"][0]["seen_count_label"] == "2회 포착"

    assert etf_alias_response.status_code == 200
    etf_payload = etf_alias_response.get_json()
    assert etf_payload["model_code"] == "T-ETF-V01"
    assert etf_payload["bucket_counts"] == {"confirmed": 1, "near": 2, "observe": 0}
    assert etf_payload["top_by_bucket"]["observe"] == []
    assert etf_payload["top_by_bucket"]["confirmed"][0]["role_key"] == "CORE_BETA"
    assert etf_payload["top_by_bucket"]["confirmed"][0]["role_confidence"] == 0.92
    assert (
        etf_payload["top_by_bucket"]["confirmed"][0]["role_reason"]
        == "대표 미국 주식 지수 노출 ETF입니다."
    )
    assert etf_payload["shadow_summary"]["confirmed"]["avg_stage1_prob"] == 0.626
    assert etf_payload["performance_summary"]["period_metrics"][0]["period"] == "6M"
    assert etf_payload["rolling_watchlist"]["summary_rows"][0]["count"] == 2
    assert etf_payload["rolling_watchlist"]["items"][0]["seen_count_label"] == "1개월"
    assert etf_payload["rolling_watchlist"]["items"][0]["role_key"] == "CORE_BETA"


def test_tseries_public_page_renders_and_handles_empty_bucket(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/discovery")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert client.get("/new-entries").status_code == 404
    assert client.get("/investment-portfolio").status_code == 404
    assert "상승종목 발굴" in body
    assert "전이형 발굴 모델" in body
    assert "T-STOCK-V01" in body
    assert "T-ETF-V01" in body
    assert "대우건설" in body
    assert "현재 후보가 없습니다." in body
    assert "성과 요약" in body
    assert "Total Return" in body
    assert "shadow discovery basket" in body
    assert "Equal-weight basket of confirmed and near candidates" in body
    assert "주식" in body and "ETF" in body
    assert "핵심지수형" in body
    assert "스타일/팩터형" in body
    assert "누적 관찰 후보" in body
    assert "신규 1" in body
    assert "유지 0" in body
    assert "쿨링 10" in body
    assert "2회 포착" in body
    assert "상승종목 발굴 일간 신호 데이터가 아직 준비되지 않았습니다." in body
    assert 'class="discovery-name-cell">대우건설<' in body
    assert 'class="feature-grid three-up discovery-candidate-grid"' in body
    assert 'class="feature-card shell-card discovery-candidate-card"' in body
    assert 'class="discovery-candidate-table"' in body
    assert "<td>5Y</td>" not in body
    assert "<td>FULL</td>" not in body


def test_tseries_public_page_renders_trading_sign_block_when_available(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    seed_tseries_discovery_trading_sign_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/discovery")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert body.count("일간 관찰 신호(전일 종가 기준)") >= 2
    assert (
        "관찰 종목 신호" in body
        or "상승종목 발굴 일간 신호 데이터가 아직 준비되지 않았습니다." in body
    )
    assert "추천 종목 신호" not in body
    assert "매수 대기" not in body
    assert "대우건설" in body


def test_tseries_public_page_hides_missing_trading_sign_sections_gracefully(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    body = client.get("/discovery").get_data(as_text=True)

    assert "상승종목 발굴 일간 신호 데이터가 아직 준비되지 않았습니다." in body
    assert "대우건설" in body


def test_tseries_public_page_hides_missing_rolling_watchlist_gracefully(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    payload_path = (
        settings.public_data_dir
        / "tseries_discovery"
        / "current"
        / "quantservice_tseries_discovery.json"
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["models"][0].pop("rolling_watchlist", None)
    payload["models"][1].pop("rolling_watchlist", None)
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    app = create_app(settings)
    client = app.test_client()
    body = client.get("/discovery").get_data(as_text=True)

    assert "상승종목 발굴 rolling watchlist 데이터가 아직 준비되지 않았습니다." in body
    assert "대우건설" in body


def test_home_renders_tseries_teaser_when_available(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_user_snapshot(settings.user_snapshot_dir)
    seed_market_analysis_snapshot(settings.market_analysis_dir)
    seed_tseries_discovery_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "상승종목 발굴" in body
    assert "후보 상세 보기" not in body


def test_tseries_remote_current_uses_cache_buster_and_no_cache_headers(
    tmp_path: Path, monkeypatch
) -> None:
    settings = build_settings(tmp_path)
    api = TSeriesOperationalApi(
        settings.__class__(
            **{
                **settings.__dict__,
                "snapshot_source": "remote",
                "snapshot_gcs_base_url": "https://storage.googleapis.com/quantservice-489808-market-analysis",
            }
        )
    )
    captured: dict[str, object] = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return (
                b'{"source_name":"remote:test","models":[{"'
                b'model_code":"T-STOCK-V01","asof_date":"2026-03-26"}]}'
            )

    def fake_urlopen(request, timeout=10):
        captured["request"] = request
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("service_platform.web.tseries_api.urlopen", fake_urlopen)

    overview = api.load_overview(force_refresh=True)
    request = captured["request"]

    assert overview.source_name == "remote:test"
    assert captured["timeout"] == 10
    assert request.full_url.startswith(
        "https://storage.googleapis.com/quantservice-489808-market-analysis/"
        "tseries_discovery/current/quantservice_tseries_discovery.json?ts="
    )
    assert request.headers["Cache-control"] == "no-cache"
    assert request.headers["Pragma"] == "no-cache"
    assert api._with_cache_buster("file:///tmp/test.json", "123") == "file:///tmp/test.json"


def test_tseries_api_can_read_remote_current_payload(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    remote_root = tmp_path / "remote_payload"
    seed_tseries_discovery_payload(remote_root)

    remote_payload_path = (
        remote_root / "tseries_discovery" / "current" / "quantservice_tseries_discovery.json"
    )
    remote_payload = json.loads(remote_payload_path.read_text(encoding="utf-8"))
    remote_payload["source_name"] = "remote:tseries_discovery_current"
    remote_payload["models"][0]["asof_date"] = "2026-04-01"
    remote_payload["models"][0]["bucket_counts"] = {
        "confirmed": 7,
        "near": 4,
        "observe": 2,
    }
    remote_payload["models"][1]["shadow_summary"] = {
        "historical_stage2": {
            "obs_n": 69,
            "t10_hit_rate": 17.4,
            "t3_hit_rate": 8.7,
            "avg_stage1_prob": 0.626,
            "avg_stage2_prob": 0.551,
        },
        "historical_stage1": {
            "obs_n": 698,
            "t10_hit_rate": 7.0,
            "t3_hit_rate": 3.1,
            "avg_stage1_prob": 0.601,
            "avg_stage2_prob": None,
        },
    }
    remote_payload_path.write_text(
        json.dumps(remote_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    remote_settings = settings.__class__(
        **{
            **settings.__dict__,
            "snapshot_source": "remote",
            "snapshot_gcs_base_url": remote_root.as_uri(),
        }
    )
    app = create_app(remote_settings)
    client = app.test_client()

    list_response = client.get("/api/v1/discovery/t-series")
    detail_response = client.get("/api/v1/discovery/t-series/T-STOCK-V01")
    etf_detail_response = client.get("/api/v1/discovery/t-series/T-ETF-V01")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert etf_detail_response.status_code == 200
    assert list_response.get_json()["source_name"] == "remote:tseries_discovery_current"
    assert detail_response.get_json()["asof_date"] == "2026-04-01"
    assert detail_response.get_json()["bucket_counts"] == {
        "confirmed": 7,
        "near": 4,
        "observe": 2,
    }
    assert etf_detail_response.get_json()["shadow_summary"]["confirmed"]["obs_n"] == 69
    assert etf_detail_response.get_json()["shadow_summary"]["near"]["obs_n"] == 698


def test_tseries_api_remote_current_falls_back_to_local_payload(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    remote_root = tmp_path / "missing_remote_payload"
    remote_settings = settings.__class__(
        **{
            **settings.__dict__,
            "snapshot_source": "remote",
            "snapshot_gcs_base_url": remote_root.as_uri(),
        }
    )
    app = create_app(remote_settings)
    client = app.test_client()

    list_response = client.get("/api/v1/discovery/t-series")
    detail_response = client.get("/api/v1/discovery/t-series/T-STOCK-V01")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert list_response.get_json()["source_name"] == "handoff:tseries_discovery"
    assert detail_response.get_json()["asof_date"] == "2026-03-26"
    assert (
        "원격 T-series discovery payload를 읽지 못해 로컬 current 데이터를 사용합니다."
        in list_response.get_json()["warnings"]
    )
    assert any(
        "Failed to load T-series discovery payload" in error
        for error in list_response.get_json()["errors"]
    )


def test_tseries_api_returns_503_when_payload_is_missing(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    app = create_app(settings)
    client = app.test_client()

    list_response = client.get("/api/v1/discovery/t-series")
    page_response = client.get("/discovery")

    assert list_response.status_code == 503
    assert page_response.status_code == 503
