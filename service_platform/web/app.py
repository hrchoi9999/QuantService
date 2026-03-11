from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from service_platform.access.store import (
    AccessContext,
    AccessStore,
    GrantValidationError,
    LoginValidationError,
    build_today_sections,
)
from service_platform.billing import BillingDisabledError, BillingService, LightPayValidationError
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

STATUS_MESSAGES = {
    "invalid": "이메일 또는 비밀번호를 다시 확인해 주세요.",
    "logged_out": "로그아웃되었습니다.",
    "granted": "플랜이 적용되었습니다.",
    "revoked": "플랜이 회수되었습니다.",
    "error": "요청을 처리하지 못했습니다. 입력값을 다시 확인해 주세요.",
}

BILLING_MESSAGES = {
    "disabled": "현재 결제 기능은 비활성화되어 있습니다.",
    "login_required": "결제를 진행하려면 먼저 로그인해 주세요.",
    "invalid": "결제 요청을 처리하지 못했습니다. 결제수단과 플랜을 다시 확인해 주세요.",
}


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


def _safe_next_url(candidate: str | None) -> str:
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for("today")


def _admin_redirect_url(access_key: str | None, *, status: str) -> str:
    params = {"status": status}
    if access_key:
        params["access_key"] = access_key
    return f"{url_for('admin_grant')}?{urlencode(params)}"


def _request_ip_address() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_notify_ip_allowed(settings: Settings) -> bool:
    if not settings.lightpay_notify_allowed_ips:
        return True
    return _request_ip_address() in settings.lightpay_notify_allowed_ips


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    logger = configure_logging(settings.log_level)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = settings.session_secret_key
    provider = SnapshotDataProvider(settings)
    feedback_store = FeedbackStore(settings)
    access_store = AccessStore(settings)
    billing_service = BillingService(settings, access_store)

    app.config["SETTINGS"] = settings
    app.config["SNAPSHOT_PROVIDER"] = provider
    app.config["FEEDBACK_STORE"] = feedback_store
    app.config["ACCESS_STORE"] = access_store
    app.config["BILLING_SERVICE"] = billing_service

    def current_access_context() -> AccessContext:
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            return access_store.get_effective_access(None)
        return access_store.get_effective_access(user_id)

    def current_user_orders() -> list[dict]:
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            return []
        return access_store.list_orders_for_user(user_id)

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        access_context = current_access_context()
        return {
            "service_name": "redbot",
            "current_user": access_context.user,
            "access_context": access_context,
            "status_messages": STATUS_MESSAGES,
            "billing_enabled": settings.billing_enabled,
            "billing_messages": BILLING_MESSAGES,
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
        access_context = current_access_context()
        meta["effective_plan_id"] = access_context.effective_plan_id
        if bundle and bundle.generated_at:
            meta["publish_generated_at"] = bundle.generated_at
        safe_record_event(event_name="page_view", page=page, meta=meta)

    def ensure_billing_enabled() -> None:
        if not settings.billing_enabled:
            abort(404)

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

    @app.get("/theme-preview")
    def theme_preview() -> Response:
        record_page_view("/theme-preview")
        return Response(
            render_template("theme_preview.html", page_title="Theme Preview"),
            mimetype="text/html",
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Response:
        next_url = _safe_next_url(request.values.get("next"))
        if request.method == "GET":
            record_page_view("/login")
            return Response(
                render_template(
                    "login.html",
                    page_title="Login",
                    status=request.args.get("status", ""),
                    next_url=next_url,
                ),
                mimetype="text/html",
            )

        try:
            user = access_store.authenticate_or_register(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
            )
        except LoginValidationError:
            return redirect(url_for("login", status="invalid", next=next_url))

        session.clear()
        session["user_id"] = user.id
        return redirect(next_url)

    @app.route("/logout", methods=["GET", "POST"])
    def logout() -> Response:
        session.clear()
        return redirect(url_for("login", status="logged_out"))

    @app.get("/me")
    def me() -> tuple[dict[str, object], int]:
        access_context = current_access_context()
        user = access_context.user
        return (
            jsonify(
                {
                    "authenticated": access_context.authenticated,
                    "email": user.email if user else None,
                    "roles": list(access_context.roles),
                    "base_plan_id": access_context.base_plan_id,
                    "effective_plan_id": access_context.effective_plan_id,
                    "trial_active": access_context.trial_active,
                    "trial_end_date": access_context.trial_end_date,
                    "entitlements": access_context.entitlements,
                    "is_admin": access_context.is_admin,
                    "recent_orders": current_user_orders(),
                }
            ),
            200,
        )

    @app.get("/pricing")
    def pricing() -> Response:
        access_context = current_access_context()
        record_page_view("/pricing")
        return Response(
            render_template(
                "pricing.html",
                page_title="Pricing",
                plan_rows=billing_service.list_paid_plans(),
                billing_enabled=settings.billing_enabled,
                selected_method=request.args.get("pay_method", "CARD"),
                status=request.args.get("status", ""),
                current_orders=current_user_orders(),
                access_context=access_context,
            ),
            mimetype="text/html",
        )

    @app.post("/billing/checkout")
    def billing_checkout() -> Response:
        ensure_billing_enabled()
        access_context = current_access_context()
        if not access_context.authenticated or access_context.user is None:
            return redirect(url_for("login", next=url_for("pricing"), status="invalid"))

        try:
            form, ord_no = billing_service.create_checkout(
                user_id=access_context.user.id,
                user_email=access_context.user.email,
                plan_id=request.form.get("plan_id", ""),
                pay_method=request.form.get("pay_method", ""),
            )
        except (BillingDisabledError, LightPayValidationError):
            return redirect(url_for("pricing", status="invalid"))

        return Response(
            render_template(
                "billing_checkout.html",
                page_title="Billing Checkout",
                checkout_form=form,
                ord_no=ord_no,
            ),
            mimetype="text/html",
        )

    @app.route("/billing/return", methods=["GET", "POST"])
    def billing_return() -> Response:
        ensure_billing_enabled()
        payload = {key: value for key, value in request.values.items()}
        try:
            result = billing_service.handle_return(payload)
        except BillingDisabledError:
            abort(404)
        return Response(
            render_template(
                "billing_result.html",
                page_title="Billing Result",
                billing_result=result,
                source="return",
            ),
            mimetype="text/html",
        )

    @app.post("/billing/notify")
    def billing_notify() -> tuple[dict[str, object], int]:
        ensure_billing_enabled()
        if not _is_notify_ip_allowed(settings):
            logger.warning("billing_notify_ip_blocked ip=%s", _request_ip_address())
            return (
                jsonify({"status": "forbidden", "message": "notify sender blocked"}),
                403,
            )
        payload = {key: value for key, value in request.form.items()}
        try:
            result = billing_service.handle_notify(payload)
        except BillingDisabledError:
            abort(404)
        status_code = 200 if result.status in {"approved", "duplicate", "ignored"} else 400
        return (
            jsonify(
                {
                    "status": result.status,
                    "message": result.message,
                    "ord_no": result.ord_no,
                    "plan_id": result.plan_id,
                    "duplicate": result.duplicate,
                }
            ),
            status_code,
        )

    @app.get("/today")
    def today() -> Response | tuple[str, int]:
        bundle = load_or_error()
        if bundle is None:
            return render_snapshot_error()
        access_context = current_access_context()
        today_sections = build_today_sections(
            bundle.daily_recommendations.get("models", []),
            access_context.entitlements,
        )
        record_page_view("/today", bundle)
        for section in today_sections:
            safe_record_event(
                event_name="model_section_view",
                page="/today",
                model_id=section.get("model_id"),
            )
        return Response(
            render_template(
                "today.html",
                page_title="Today",
                bundle=bundle,
                ticker_target_url=_ticker_target_url,
                today_sections=today_sections,
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
        access_context = current_access_context()
        if not is_admin_request(request, settings, access_context):
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

    @app.route("/admin/grant", methods=["GET", "POST"])
    def admin_grant() -> Response:
        access_context = current_access_context()
        access_key = request.values.get("access_key") or request.args.get("access_key")
        if not is_admin_request(request, settings, access_context):
            abort(404)

        if request.method == "POST":
            action = request.form.get("action", "grant")
            try:
                if action == "revoke":
                    access_store.revoke_plan(email=request.form.get("email", ""))
                    status = "revoked"
                else:
                    access_store.grant_plan(
                        email=request.form.get("email", ""),
                        plan_id=request.form.get("plan_id", "free"),
                        expires_at=request.form.get("expires_at", "").strip() or None,
                    )
                    status = "granted"
            except GrantValidationError:
                status = "error"
            return redirect(_admin_redirect_url(access_key, status=status))

        record_page_view("/admin/grant")
        return Response(
            render_template(
                "admin_grant.html",
                page_title="Admin Grant",
                status=request.args.get("status", ""),
                plan_rows=access_store.list_plans(),
                access_key=access_key or "",
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
                    "billing_enabled": settings.billing_enabled,
                }
            ),
            200,
        )

    return app


app = create_app()


if __name__ == "__main__":
    current_settings = app.config["SETTINGS"]
    app.run(host=current_settings.web_host, port=current_settings.web_port)
