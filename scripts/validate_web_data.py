from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing required web data file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return payload


def parse_date(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def first_value(payload: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def assert_fresh(
    label: str,
    payload: dict[str, Any],
    names: tuple[str, ...],
    max_age_days: int,
) -> None:
    value = first_value(payload, names)
    if not value:
        raise RuntimeError(f"{label} is missing date metadata")
    try:
        parsed = parse_date(value)
    except ValueError as exc:
        raise RuntimeError(f"{label} has invalid date metadata: {value}") from exc
    age_seconds = (
        datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    ).total_seconds()
    age_days = age_seconds / 86400
    if age_days > max_age_days:
        raise RuntimeError(f"{label} is stale: {value} (max {max_age_days}d)")


def assert_json_data(
    label: str,
    path: Path,
    names: tuple[str, ...],
    max_age_days: int,
) -> dict[str, Any]:
    payload = read_json(path)
    assert_fresh(label, payload, names, max_age_days)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--user-max-age-days", type=int, default=10)
    parser.add_argument("--market-max-age-days", type=int, default=2)
    parser.add_argument("--portfolio-max-age-days", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root)
    public_dir = root / "service_platform" / "web" / "public_data"
    admin_dir = root / "service_platform" / "web" / "admin_data" / "current"
    user_dir = public_dir / "user_current"
    market_dir = public_dir / "market_analysis" / "current"
    tseries_dir = public_dir / "tseries_discovery" / "current"
    date_fields = ("generated_at", "as_of_date", "asof")
    market_date_fields = ("asof", "generated_at", "as_of_date")

    assert_json_data(
        "Quant user publish manifest",
        user_dir / "publish_manifest.json",
        date_fields,
        args.user_max_age_days,
    )
    assert_json_data(
        "Quant user model snapshot",
        user_dir / "user_model_snapshot_report.json",
        date_fields,
        args.user_max_age_days,
    )
    assert_json_data(
        "T-series discovery",
        tseries_dir / "quantservice_tseries_discovery.json",
        date_fields,
        args.user_max_age_days,
    )

    market_manifest = assert_json_data(
        "QuantMarket manifest",
        market_dir / "quantservice_market_manifest.json",
        market_date_fields,
        args.market_max_age_days,
    )
    if "files" not in market_manifest:
        raise RuntimeError("QuantMarket manifest is missing files metadata")
    assert_json_data(
        "QuantMarket page",
        market_dir / "quantservice_market_page.json",
        market_date_fields,
        args.market_max_age_days,
    )
    assert_json_data(
        "QuantMarket today",
        market_dir / "quantservice_market_today.json",
        market_date_fields,
        args.market_max_age_days,
    )
    assert_json_data(
        "Market environment indicators",
        market_dir / "quantservice_market_environment_indicators.json",
        market_date_fields,
        args.market_max_age_days,
    )

    portfolio = assert_json_data(
        "Investment portfolio",
        admin_dir / "investment_portfolio_latest.json",
        date_fields,
        args.portfolio_max_age_days,
    )
    for field in ("market_risk", "stock_strategy", "final_portfolio_strategy"):
        if field not in portfolio:
            raise RuntimeError(f"Investment portfolio is missing required field: {field}")

    print("Web data validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
