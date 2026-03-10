"""S2 adapter for converting quant CSV outputs into service schema payloads."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from service_platform.publishers.adapters.common import (
    determine_change_type,
    normalize_score,
    normalize_stock_name,
    normalize_ticker,
    summarize_reason,
)

MODEL_ID = "s2_regime_growth"
MODEL_NAME = "S2 Regime Growth"
MODEL_SUMMARY = "Selects growth candidates while respecting regime and market gate conditions."
MODEL_STYLE = "Regime + Growth"
MODEL_RISK_NOTE = "Signals can turn defensive quickly when regime or market filters weaken."
DEFAULT_DISCLAIMER = (
    "This material is for informational purposes only and is not investment advice."
)
NO_CHANGE_SUMMARY = "No material rank changes were detected beyond the selected sample window."


@dataclass(frozen=True)
class S2AdapterInput:
    holdings_csv: Path
    snapshot_csv: Path
    summary_csv: Path


class S2Adapter:
    def __init__(self, adapter_input: S2AdapterInput) -> None:
        self.adapter_input = adapter_input

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _load_holdings(self) -> list[dict[str, Any]]:
        rows = []
        for row in self._read_csv(self.adapter_input.holdings_csv):
            if str(row.get("ticker", "")).strip().upper() == "CASH":
                continue
            rows.append(
                {
                    **row,
                    "ticker": normalize_ticker(row["ticker"]),
                    "score_rank": int(float(row["score_rank"])),
                    "growth_score": normalize_score(row.get("growth_score")),
                    "rebalance_date": datetime.strptime(row["rebalance_date"], "%Y-%m-%d").date(),
                }
            )
        return rows

    def _load_snapshot(self) -> dict[str, dict[str, Any]]:
        latest_by_ticker: dict[str, dict[str, Any]] = {}
        for row in self._read_csv(self.adapter_input.snapshot_csv):
            ticker = normalize_ticker(row["ticker"])
            snapshot_date = datetime.strptime(row["snapshot_date"], "%Y-%m-%d").date()
            current = latest_by_ticker.get(ticker)
            if current is None or snapshot_date >= current["snapshot_date"]:
                latest_by_ticker[ticker] = {
                    **row,
                    "ticker": ticker,
                    "snapshot_date": snapshot_date,
                }
        return latest_by_ticker

    def _load_summary(self) -> dict[str, str]:
        rows = self._read_csv(self.adapter_input.summary_csv)
        return rows[0]

    def _current_and_previous_holdings(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        holdings = self._load_holdings()
        dates = sorted({row["rebalance_date"] for row in holdings})
        current_date = dates[-1]
        previous_date = dates[-2] if len(dates) > 1 else None
        current = [row for row in holdings if row["rebalance_date"] == current_date]
        previous = [row for row in holdings if row["rebalance_date"] == previous_date]
        return current, previous

    def _with_names(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshot_map = self._load_snapshot()
        enriched = []
        for row in rows:
            snapshot = snapshot_map.get(row["ticker"], {})
            enriched.append(
                {
                    **row,
                    "stock_name": normalize_stock_name(snapshot.get("name"), row["ticker"]),
                }
            )
        return enriched

    def build_model_catalog_entry(self) -> dict[str, Any]:
        return {
            "model_id": MODEL_ID,
            "model_name": MODEL_NAME,
            "summary": MODEL_SUMMARY,
            "style": MODEL_STYLE,
            "risk_note": MODEL_RISK_NOTE,
            "is_active": True,
        }

    def build_daily_recommendations(self) -> dict[str, Any]:
        current, previous = self._current_and_previous_holdings()
        current = self._with_names(current)
        current = sorted(current, key=lambda row: (row["score_rank"], row["ticker"]))
        previous_rank_map = {row["ticker"]: row["score_rank"] for row in previous}

        top_picks = []
        for index, row in enumerate(current, start=1):
            score = normalize_score(row.get("growth_score"))
            change_type = determine_change_type(previous_rank_map.get(row["ticker"]), index)
            top_picks.append(
                {
                    "rank": index,
                    "ticker": row["ticker"],
                    "stock_name": row["stock_name"],
                    "score": score,
                    "reason_summary": summarize_reason(
                        regime=row.get("regime"),
                        score=score,
                        market_ok=row.get("market_ok"),
                    ),
                    "change_type": change_type,
                }
            )

        as_of_date = current[0]["rebalance_date"].isoformat()
        return {
            "as_of_date": as_of_date,
            "generated_at": f"{as_of_date}T00:00:00Z",
            "models": [{"model_id": MODEL_ID, "top_picks": top_picks}],
            "disclaimer": DEFAULT_DISCLAIMER,
        }

    def build_recent_changes(self) -> dict[str, Any]:
        current, previous = self._current_and_previous_holdings()
        current = self._with_names(current)
        current = sorted(current, key=lambda row: (row["score_rank"], row["ticker"]))
        previous = sorted(previous, key=lambda row: (row["score_rank"], row["ticker"]))
        previous_rank_map = {row["ticker"]: index for index, row in enumerate(previous, start=1)}
        current_rank_map = {row["ticker"]: index for index, row in enumerate(current, start=1)}
        current_name_map = {row["ticker"]: row["stock_name"] for row in current}

        changes: list[dict[str, Any]] = []
        for ticker, rank in current_rank_map.items():
            previous_rank = previous_rank_map.get(ticker)
            stock_name = current_name_map[ticker]
            if previous_rank is None:
                changes.append(
                    {
                        "model_id": MODEL_ID,
                        "ticker": ticker,
                        "stock_name": stock_name,
                        "event": "new_entry",
                        "summary": f"{stock_name} entered the latest S2 selection at rank {rank}.",
                    }
                )
            elif previous_rank > rank:
                summary = f"{stock_name} improved from rank {previous_rank} to rank {rank}."
                changes.append(
                    {
                        "model_id": MODEL_ID,
                        "ticker": ticker,
                        "stock_name": stock_name,
                        "event": "rank_up",
                        "summary": summary,
                    }
                )
            elif previous_rank < rank:
                changes.append(
                    {
                        "model_id": MODEL_ID,
                        "ticker": ticker,
                        "stock_name": stock_name,
                        "event": "rank_down",
                        "summary": f"{stock_name} moved from rank {previous_rank} to rank {rank}.",
                    }
                )

        snapshot_map = self._load_snapshot()
        for ticker in sorted(set(previous_rank_map) - set(current_rank_map)):
            stock_name = normalize_stock_name(snapshot_map.get(ticker, {}).get("name"), ticker)
            changes.append(
                {
                    "model_id": MODEL_ID,
                    "ticker": ticker,
                    "stock_name": stock_name,
                    "event": "exit",
                    "summary": f"{stock_name} dropped out of the latest S2 selection.",
                }
            )

        if not changes and current:
            changes.append(
                {
                    "model_id": MODEL_ID,
                    "ticker": current[0]["ticker"],
                    "stock_name": current[0]["stock_name"],
                    "event": "rank_up",
                    "summary": NO_CHANGE_SUMMARY,
                }
            )

        as_of_date = current[0]["rebalance_date"].isoformat()
        return {"as_of_date": as_of_date, "changes": changes}

    def build_performance_summary(self) -> dict[str, Any]:
        summary = self._load_summary()
        return {
            "models": [
                {
                    "model_id": MODEL_ID,
                    "cagr": normalize_score(summary.get("cagr")),
                    "mdd": normalize_score(summary.get("mdd")),
                    "sharpe": normalize_score(summary.get("sharpe")),
                    "note": "Backtest summary imported from the S2 CSV export.",
                }
            ]
        }

    def build_model_catalog(self) -> dict[str, Any]:
        return {"models": [self.build_model_catalog_entry()]}

    def build_service_payloads(self) -> dict[str, dict[str, Any]]:
        return {
            "model_catalog": self.build_model_catalog(),
            "daily_recommendations": self.build_daily_recommendations(),
            "recent_changes": self.build_recent_changes(),
            "performance_summary": self.build_performance_summary(),
        }
