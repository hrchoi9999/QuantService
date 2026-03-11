from __future__ import annotations

from datetime import datetime

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from service_platform.feedback.handlers import (
    build_feedback_redirect,
    build_feedback_submission,
    is_admin_request,
)
from service_platform.feedback.storage import (
    FeedbackDuplicateError,
    FeedbackRateLimitError,
    FeedbackStore,
    FeedbackValidationError,
)
from service_platform.shared.config import Settings, get_settings
from service_platform.shared.logging import configure_logging
from service_platform.shared.notifications import send_alert
from service_platform.web.data_provider import SnapshotDataProvider, SnapshotLoadError


def _format_datetime(value: str | None) -> str:
    if not value:
        return "Unavailable"

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _format_percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _ticker_target_url(ticker: str) -> str:
    return f"https://finance.naver.com/item/main.naver?code={ticker}"


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    logger = configure_logging(settings.log_level)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    provider = SnapshotDataProvider(settings)
    feedback_store = FeedbackStore(settings)

    app.config["SETTINGS"] = settings
    app.config["SNAPSHOT_PROVIDER"] = provider
    app.config["FEEDBACK_STORE"] = feedback_store

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        return {
            "service_name": "redbot",
        }

    @app.template_filter("fmt_datetime")
    def fmt_datetime(value: str | None) -> str:
        return _format_datetime(value)

    @app.template_filter("fmt_percent")
    def fmt_percent(value: float | int | None) -> str:
        return _format_percent(value)

    def safe_metrics_summary() -> dict:
        try:
            return feedback_store.get_metrics_summary()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("metrics_summary_failed error=%s", exc)
            return {
                "window_hours": settings.analytics_window_hours,
                "page_views": 0,
                "today_page_views": 0,
                "feedback_submissions": 0,
                "ticker_clicks": [],
                "model_interest": [],
            }

    def safe_record_event(**kwargs) -> None:
        try:
            feedback_store.record_event(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("event_record_failed error=%s", exc)

    def safe_list_recent_feedback(limit: int = 100) -> list[dict]:
        try:
            return feedback_store.list_recent_feedback(limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("feedback_list_failed error=%s", exc)
            return []

    def maybe_alert_status(status_snapshot) -> None:
        if status_snapshot.state == "healthy":
            return
        send_alert(
            settings,
            title="Snapshot Status Warning",
            message=(
                f"state={status_snapshot.state} as_of={status_snapshot.as_of_date} "
                f"run_id={status_snapshot.last_run_id} errors={' | '.join(status_snapshot.errors)}"
            ),
            alert_key=f"snapshot_status_{status_snapshot.state}",
        )

    def render_snapshot_error(status_code: int = 503) -> tuple[str, int]:
        status_snapshot = provider.get_status(force_refresh=False)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        return (
            render_template(
                "error.html",
                page_title="Snapshot Unavailable",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                message="현재 데이터 업데이트 중입니다. 잠시 후 다시 시도해 주세요.",
            ),
            status_code,
        )

    def load_or_error():
        try:
            return provider.load_bundle(force_refresh=False)
        except SnapshotLoadError:
            return None

    def record_page_view(page: str, bundle=None) -> None:
        meta = {}
        if bundle and bundle.generated_at:
            meta["publish_generated_at"] = bundle.generated_at
        safe_record_event(event_name="page_view", page=page, meta=meta)

    @app.get("/")
    def home() -> Response | tuple[str, int]:
        bundle = load_or_error()
        if bundle is None:
            return render_snapshot_error()
        record_page_view("/", bundle)
        return Response(
            render_template("home.html", page_title="Home", bundle=bundle),
            mimetype="text/html",
        )

    @app.get("/today")
    def today() -> Response | tuple[str, int]:
        bundle = load_or_error()
        if bundle is None:
            return render_snapshot_error()
        record_page_view("/today", bundle)
        for model in bundle.daily_recommendations.get("models", []):
            safe_record_event(
                event_name="model_section_view",
                page="/today",
                model_id=model.get("model_id"),
            )
        return Response(
            render_template(
                "today.html",
                page_title="Today",
                bundle=bundle,
                ticker_target_url=_ticker_target_url,
            ),
            mimetype="text/html",
        )

    @app.get("/changes")
    def changes() -> Response | tuple[str, int]:
        bundle = load_or_error()
        if bundle is None:
            return render_snapshot_error()
        record_page_view("/changes", bundle)
        return Response(
            render_template("changes.html", page_title="Changes", bundle=bundle),
            mimetype="text/html",
        )

    @app.get("/performance")
    def performance() -> Response | tuple[str, int]:
        bundle = load_or_error()
        if bundle is None:
            return render_snapshot_error()
        record_page_view("/performance", bundle)
        return Response(
            render_template("performance.html", page_title="Performance", bundle=bundle),
            mimetype="text/html",
        )

    @app.get("/feedback")
    def feedback() -> Response:
        record_page_view("/feedback")
        return Response(
            render_template(
                "feedback.html",
                page_title="Feedback",
                status=request.args.get("status", ""),
            ),
            mimetype="text/html",
        )

    @app.post("/feedback")
    def submit_feedback() -> Response:
        submission = build_feedback_submission(request)
        try:
            feedback_store.submit_feedback(submission)
            return redirect(build_feedback_redirect(url_for("feedback"), status="success"))
        except FeedbackValidationError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="invalid"))
        except FeedbackRateLimitError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="rate_limited"))
        except FeedbackDuplicateError:
            return redirect(build_feedback_redirect(url_for("feedback"), status="duplicate"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("feedback_submit_failed error=%s", exc)
            send_alert(
                settings,
                title="Feedback Submit Failed",
                message=f"Feedback submit failed on page={submission.page}: {exc}",
                alert_key="feedback_submit_failed",
            )
            return redirect(build_feedback_redirect(url_for("feedback"), status="error"))

    @app.get("/privacy")
    def privacy() -> Response:
        record_page_view("/privacy")
        return Response(
            render_template("privacy.html", page_title="Privacy"),
            mimetype="text/html",
        )

    @app.get("/e/click")
    def track_click() -> Response:
        ticker = request.args.get("ticker", "")
        model_id = request.args.get("model_id", "")
        target = request.args.get("target") or _ticker_target_url(ticker)
        if not ticker:
            abort(400)
        safe_record_event(
            event_name="ticker_click",
            page=request.args.get("page", "/today"),
            model_id=model_id or None,
            ticker=ticker,
            meta={"target": target},
        )
        return redirect(target)

    @app.get("/admin/feedback")
    def admin_feedback() -> Response:
        if not is_admin_request(request, settings):
            abort(404)
        feedback_rows = safe_list_recent_feedback(limit=100)
        metrics_summary = safe_metrics_summary()
        return Response(
            render_template(
                "admin_feedback.html",
                page_title="Admin Feedback",
                feedback_rows=feedback_rows,
                metrics_summary=metrics_summary,
            ),
            mimetype="text/html",
        )

    @app.get("/status")
    def status() -> Response:
        force_refresh = request.args.get("refresh") == "1"
        status_snapshot = provider.get_status(force_refresh=force_refresh)
        maybe_alert_status(status_snapshot)
        metrics_summary = safe_metrics_summary()
        return Response(
            render_template(
                "status.html",
                page_title="Status",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
            ),
            mimetype="text/html",
        )

    @app.get("/healthz")
    @app.get("/health")
    def healthz() -> tuple[dict[str, object], int]:
        status_snapshot = provider.get_status(force_refresh=False)
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
                    "last_run_id": status_snapshot.last_run_id,
                    "feedback_submissions_24h": metrics_summary["feedback_submissions"],
                }
            ),
            200,
        )

    return app


app = create_app()


if __name__ == "__main__":
    current_settings = app.config["SETTINGS"]
    app.run(host=current_settings.web_host, port=current_settings.web_port)
