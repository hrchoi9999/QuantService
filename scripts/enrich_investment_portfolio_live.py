from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from service_platform.web.investment_portfolio_api import (
    QUANT_ANALYSIS_DB_PATH,
    enrich_portfolio_payload_with_db_live,
)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"portfolio payload root must be object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio-json", required=True)
    parser.add_argument("--db-path", default=str(QUANT_ANALYSIS_DB_PATH))
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_json)
    payload = read_json(portfolio_path)
    result = enrich_portfolio_payload_with_db_live(payload, Path(args.db_path))
    if result.get("status") == "updated":
        portfolio_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
