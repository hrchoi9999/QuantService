from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

from service_platform.shared.config import Settings


def register_status_routes(
    app: Flask,
    *,
    settings: Settings,
    user_snapshot_api: Any,
    market_analysis_api: Any,
    maybe_alert_status: Callable[[Any], None],
    safe_metrics_summary: Callable[[], dict[str, Any]],
) -> None:
    @app.get("/status")
    def status() -> Response:
        force_refresh = request.args.get("refresh") == "1"
        status_snapshot = user_snapshot_api.get_status(force_refresh=force_refresh)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        publish_status_payload = None
        if status_snapshot.snapshot_accessible:
            publish_status_payload = user_snapshot_api.get_publish_status(
                force_refresh=force_refresh
            )
        return Response(
            render_template(
                "status.html",
                page_title="서비스 상태",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                publish_status_payload=publish_status_payload,
            ),
            mimetype="text/html",
        )

    @app.get("/healthz")
    @app.get("/health")
    def healthz() -> tuple[Response, int]:
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        return (
            jsonify(
                {
                    "status": "ok",
                    "app_env": settings.app_env,
                    "snapshot_state": status_snapshot.state,
                    "snapshot_accessible": status_snapshot.snapshot_accessible,
                    "as_of_date": status_snapshot.as_of_date,
                    "generated_at": status_snapshot.generated_at,
                    "age_seconds": status_snapshot.age_seconds,
                    "feedback_submissions_24h": metrics_summary["feedback_submissions"],
                    "billing_enabled": settings.billing_enabled,
                    "market_analysis_state": market_analysis_api.get_status(
                        force_refresh=False
                    ).state,
                }
            ),
            200,
        )
