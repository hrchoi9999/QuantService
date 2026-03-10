from pathlib import Path

from service_platform.publishers.adapters.s2_adapter import S2Adapter, S2AdapterInput
from service_platform.publishers.writers.validate_schema import validate_payload

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "adapters" / "s2"


def build_adapter() -> S2Adapter:
    return S2Adapter(
        S2AdapterInput(
            holdings_csv=FIXTURE_DIR / "holdings.csv",
            snapshot_csv=FIXTURE_DIR / "snapshot.csv",
            summary_csv=FIXTURE_DIR / "summary.csv",
        )
    )


def test_s2_adapter_outputs_validate_against_all_service_schemas() -> None:
    payloads = build_adapter().build_service_payloads()

    for schema_name, payload in payloads.items():
        validate_payload(schema_name, payload)


def test_s2_adapter_builds_expected_daily_recommendations() -> None:
    daily = build_adapter().build_daily_recommendations()
    picks = daily["models"][0]["top_picks"]

    assert daily["as_of_date"] == "2026-03-10"
    assert [item["ticker"] for item in picks] == ["000660", "005930", "035420"]
    assert [item["change_type"] for item in picks] == ["up", "down", "new"]


def test_s2_adapter_builds_recent_changes_with_exit_event() -> None:
    changes = build_adapter().build_recent_changes()["changes"]
    events = {(item["ticker"], item["event"]) for item in changes}

    assert ("035420", "new_entry") in events
    assert ("005930", "rank_down") in events
