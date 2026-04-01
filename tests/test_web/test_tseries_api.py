import json
from pathlib import Path

from service_platform.web.app import create_app
from tests.test_web.test_health import (
    build_settings,
    seed_market_analysis_snapshot,
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
                    "display_name": "전이형 발굴 모델 · Stock",
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
                    "threshold_summary": "threshold values not published",
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
            },
        ],
    }
    (target_dir / "quantservice_tseries_discovery.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
    assert models[0]["threshold_summary"] == "stage1 0.520 / confirmed 0.525 / near 0.520"
    assert models[1]["bucket_counts"]["observe"] == 0

    assert stock_response.status_code == 200
    stock_payload = stock_response.get_json()
    assert stock_payload["meta"]["service_model_code"] == "T_STOCK_DISCOVERY"
    assert stock_payload["meta"]["display_name_ko"] == "전이형 발굴 모델"
    assert stock_payload["bucket_counts"] == {"confirmed": 6, "near": 3, "observe": 1}
    assert stock_payload["top_by_bucket"]["confirmed"][0]["ticker"] == "047040"
    assert stock_payload["top_by_bucket"]["confirmed"][2]["is_s2_overlap"] is True
    assert stock_payload["shadow_summary"]["confirmed"]["obs_n"] == 1946

    assert etf_alias_response.status_code == 200
    etf_payload = etf_alias_response.get_json()
    assert etf_payload["model_code"] == "T-ETF-V01"
    assert etf_payload["bucket_counts"] == {"confirmed": 1, "near": 2, "observe": 0}
    assert etf_payload["top_by_bucket"]["observe"] == []
    assert etf_payload["shadow_summary"]["confirmed"]["avg_stage1_prob"] == 0.626


def test_tseries_public_page_renders_and_handles_empty_bucket(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    seed_tseries_discovery_payload(settings.public_data_dir)
    app = create_app(settings)
    client = app.test_client()

    response = client.get("/discovery")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "T-series Discovery" in body
    assert "전이형 발굴 모델" in body
    assert "T-STOCK-V01" in body
    assert "T-ETF-V01" in body
    assert "대우건설" in body
    assert "현재 후보가 없습니다." in body
    assert "Stock" in body and "ETF" in body


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
    assert "T-series Discovery" in body
    assert "후보 상세 보기" in body
    assert "6" in body and "3" in body and "1" in body


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
