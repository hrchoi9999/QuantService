"""Common normalization helpers for service adapters."""

from __future__ import annotations

import math
from typing import Any


def normalize_ticker(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("ticker is required")
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return digits.zfill(6)
    return text.upper()


def normalize_stock_name(value: Any, ticker: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or f"Unknown {ticker}"


def normalize_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(score) or math.isinf(score):
        return default
    return score


def build_ranked_records(records: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: normalize_score(item.get(score_key)), reverse=True)
    for index, record in enumerate(ordered, start=1):
        record["rank"] = index
    return ordered


def determine_change_type(previous_rank: int | None, current_rank: int) -> str:
    if previous_rank is None:
        return "new"
    if previous_rank == current_rank:
        return "maintain"
    if previous_rank > current_rank:
        return "up"
    return "down"


def summarize_reason(*, regime: Any, score: float, market_ok: Any) -> str:
    fragments: list[str] = []
    if regime not in (None, ""):
        fragments.append(f"Regime {regime} is supportive")
    if score:
        fragments.append(f"score {score:.2f} remains competitive")
    if market_ok in (True, "True", "true", 1, "1"):
        fragments.append("market filter is on")
    return "; ".join(fragments) or "Model output remains valid for the current rebalance."
