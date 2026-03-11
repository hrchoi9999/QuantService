"""CLI entry point for the daily publish pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from service_platform.publishers.publish_manager import publish_daily
from service_platform.shared.config import get_settings
from service_platform.shared.notifications import send_alert

LOGGER = logging.getLogger("quantservice")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the QuantService daily publish pipeline.")
    parser.add_argument("--asof", help="Optional as-of date in YYYY-MM-DD format.")
    parser.add_argument("--models", help="Comma-separated model ids to publish.")
    parser.add_argument("--out-dir", type=Path, help="Optional publish output directory.")
    parser.add_argument("--gcs-bucket", help="Reserved for optional GCS upload support.")
    parser.add_argument(
        "--keep-days",
        type=int,
        help="Number of published version days to keep.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite safeguards for repeated runs.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    model_ids = None
    if args.models:
        model_ids = [item.strip() for item in args.models.split(",") if item.strip()]

    if args.gcs_bucket:
        print("GCS upload is not implemented in this phase. Local publish will continue.")

    try:
        result = publish_daily(
            settings=settings,
            asof=args.asof,
            model_ids=model_ids,
            out_dir=args.out_dir,
            keep_days=args.keep_days,
            force=args.force,
        )
    except Exception as exc:
        LOGGER.exception("publish_failed")
        send_alert(
            settings,
            title="Publish Failed",
            message=f"Daily publish failed for asof={args.asof or 'latest'}: {exc}",
            alert_key="publish_failed",
            force=True,
        )
        print(f"Publish failed: {exc}")
        return 2

    print(f"Publish completed. current={result.current_dir} run_id={result.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
