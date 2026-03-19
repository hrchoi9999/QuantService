from __future__ import annotations

import json
import secrets
import shutil
from datetime import datetime, timedelta
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
    AdminValidationError,
    GrantValidationError,
    LoginValidationError,
    RegistrationValidationError,
)
from service_platform.admin.auth import get_policy_state, require_admin
from service_platform.billing import BillingDisabledError, BillingService, LightPayValidationError
from service_platform.feedback.handlers import (
    build_feedback_redirect,
    build_feedback_submission,
)
from service_platform.feedback.storage import (
    FeedbackDuplicateError,
    FeedbackRateLimitError,
    FeedbackStore,
    FeedbackValidationError,
)
from service_platform.shared.config import Settings, get_settings
from service_platform.shared.constants import CURRENT_DIRNAME, MANIFEST_FILENAME, PUBLISHED_DIRNAME
from service_platform.shared.logging import configure_logging
from service_platform.shared.notifications import send_alert
from service_platform.web.data_provider import SnapshotDataProvider, SnapshotLoadError
from service_platform.web.user_snapshot_api import UserSnapshotLoadError, UserSnapshotMockApi

STATUS_MESSAGES = {
    "invalid": "이메일 또는 비밀번호를 다시 확인해 주세요.",
    "signup_success": "회원가입이 완료되었습니다. 로그인해 주세요.",
    "code_sent": "휴대폰 인증번호를 발급했습니다.",
    "verify_required": "휴대폰 인증을 먼저 완료해 주세요.",
    "email_exists": "이미 가입된 이메일입니다. 로그인해 주세요.",
    "code_invalid": "인증번호를 다시 확인해 주세요.",
    "logged_out": "로그아웃되었습니다.",
    "granted": "플랜이 적용되었습니다.",
    "revoked": "플랜이 회수되었습니다.",
    "updated": "설정이 반영되었습니다.",
    "refreshed": "캐시를 새로 고쳤습니다.",
    "activated": "선택한 스냅샷을 current로 반영했습니다.",
    "locked": "사용자를 잠금 처리했습니다.",
    "unlocked": "사용자 잠금을 해제했습니다.",
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
    user_snapshot_api = UserSnapshotMockApi(settings)
    feedback_store = FeedbackStore(settings)
    access_store = AccessStore(settings)
    billing_service = BillingService(settings, access_store)

    app.config["SETTINGS"] = settings
    app.config["SNAPSHOT_PROVIDER"] = provider
    app.config["USER_SNAPSHOT_API"] = user_snapshot_api
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

    def get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not isinstance(token, str) or not token:
            token = secrets.token_urlsafe(24)
            session["csrf_token"] = token
        return token

    def require_csrf() -> None:
        expected = session.get("csrf_token")
        provided = request.form.get("csrf_token", "")
        if not expected or not provided or provided != expected:
            abort(400)

    def _normalize_phone_number(phone_number: str) -> str:
        return "".join(ch for ch in phone_number if ch.isdigit())

    def issue_phone_verification(phone_number: str) -> str:
        normalized_phone = _normalize_phone_number(phone_number)
        if len(normalized_phone) < 10 or len(normalized_phone) > 11:
            raise RegistrationValidationError("휴대폰 번호는 숫자 10~11자리로 입력해 주세요.")
        verification_code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = (
            datetime.utcnow() + timedelta(seconds=settings.phone_verification_code_ttl_seconds)
        ).isoformat()
        session["phone_verification"] = {
            "phone_number": normalized_phone,
            "code": verification_code,
            "expires_at": expires_at,
        }
        return verification_code

    def is_phone_verification_valid(phone_number: str, verification_code: str) -> bool:
        payload = session.get("phone_verification") or {}
        if payload.get("phone_number") != _normalize_phone_number(phone_number):
            return False
        if payload.get("code") != verification_code.strip():
            return False
        expires_at = payload.get("expires_at")
        if not expires_at:
            return False
        try:
            expires = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
        if datetime.utcnow() > expires:
            return False
        return True

    def clear_phone_verification() -> None:
        session.pop("phone_verification", None)

    def current_access_key() -> str:
        value = request.values.get("access_key") or request.args.get("access_key") or ""
        return value.strip()

    def admin_url(endpoint: str, access_key: str) -> str:
        if access_key:
            return f"{url_for(endpoint)}?{urlencode({'access_key': access_key})}"
        return url_for(endpoint)

    def build_admin_links(access_key: str) -> dict[str, str]:
        links = {
            "dashboard": admin_url("admin_dashboard", access_key),
            "users": admin_url("admin_users", access_key),
            "grant": admin_url("admin_grant", access_key),
            "plans": admin_url("admin_plans_entitlements", access_key),
            "publish": admin_url("admin_publish_snapshots", access_key),
            "feedback": admin_url("admin_feedback", access_key),
            "metrics": admin_url("admin_metrics", access_key),
            "audit": admin_url("admin_audit", access_key),
        }
        if settings.billing_enabled:
            links["billing"] = admin_url("admin_billing", access_key)
        return links

    def require_admin_access() -> tuple[AccessContext, str]:
        access_context = current_access_context()
        access_key = current_access_key()
        if not require_admin(request, settings, access_context):
            abort(404)
        return access_context, access_key

    def audit_admin(
        *,
        access_context: AccessContext,
        action_type: str,
        target_type: str,
        target_id: str | None,
        payload_summary: dict | str,
        result: str,
    ) -> None:
        summary_text = (
            payload_summary
            if isinstance(payload_summary, str)
            else json.dumps(payload_summary, ensure_ascii=False, sort_keys=True)
        )
        access_store.record_audit_log(
            admin_user_id=access_context.user.id if access_context.user else None,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            payload_summary=summary_text,
            result=result,
            ip_address=_request_ip_address(),
        )

    def safe_metrics_summary() -> dict:
        try:
            return feedback_store.get_metrics_summary()
        except Exception as exc:  # pragma: no cover
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
        except Exception as exc:  # pragma: no cover
            logger.warning("event_record_failed error=%s", exc)

    def safe_list_recent_feedback(limit: int = 100) -> list[dict]:
        try:
            return feedback_store.list_recent_feedback(limit=limit)
        except Exception as exc:  # pragma: no cover
            logger.warning("feedback_list_failed error=%s", exc)
            return []

    def maybe_alert_status(status_snapshot) -> None:
        if status_snapshot.state == "healthy":
            return
        run_id = getattr(status_snapshot, "last_run_id", None)
        errors = getattr(status_snapshot, "errors", [])
        send_alert(
            settings,
            title="Snapshot Status Warning",
            message=(
                f"state={status_snapshot.state} as_of={status_snapshot.as_of_date} "
                f"run_id={run_id} errors={' | '.join(errors)}"
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

    def load_user_bundle_or_error():
        try:
            return user_snapshot_api.load_bundle(force_refresh=False)
        except UserSnapshotLoadError:
            return None

    def render_user_snapshot_error(status_code: int = 503) -> tuple[str, int]:
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        return (
            render_template(
                "error.html",
                page_title="Snapshot Unavailable",
                status_snapshot=status_snapshot,
                metrics_summary=safe_metrics_summary(),
                message="현재 사용자용 스냅샷을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            ),
            status_code,
        )

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

    def build_published_snapshot_rows() -> list[dict[str, str | None]]:
        published_root = settings.public_data_dir / PUBLISHED_DIRNAME
        if not published_root.exists():
            return []
        rows: list[dict[str, str | None]] = []
        for day_dir in sorted(
            [path for path in published_root.iterdir() if path.is_dir()], reverse=True
        ):
            for run_dir in sorted(
                [path for path in day_dir.iterdir() if path.is_dir()], reverse=True
            ):
                manifest_path = run_dir / MANIFEST_FILENAME
                manifest = {}
                if manifest_path.exists():
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                    except json.JSONDecodeError:
                        manifest = {}
                rows.append(
                    {
                        "label": run_dir.relative_to(published_root).as_posix(),
                        "as_of_date": manifest.get("as_of_date"),
                        "generated_at": manifest.get("generated_at"),
                        "run_id": manifest.get("run_id"),
                    }
                )
        return rows

    def activate_snapshot_label(snapshot_label: str) -> None:
        published_root = settings.public_data_dir / PUBLISHED_DIRNAME
        source_dir = (published_root / snapshot_label).resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise AdminValidationError("선택한 published 스냅샷을 찾지 못했습니다.")
        if published_root.resolve() not in source_dir.parents:
            raise AdminValidationError("허용되지 않은 스냅샷 경로입니다.")
        current_dir = settings.public_data_dir / CURRENT_DIRNAME
        tmp_root = settings.public_data_dir / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        staged_dir = tmp_root / f"admin-stage-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        previous_dir = tmp_root / f"admin-prev-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        shutil.copytree(source_dir, staged_dir)
        try:
            if current_dir.exists():
                current_dir.replace(previous_dir)
            staged_dir.replace(current_dir)
        finally:
            if staged_dir.exists():
                shutil.rmtree(staged_dir, ignore_errors=True)
            if previous_dir.exists():
                shutil.rmtree(previous_dir, ignore_errors=True)
        provider.load_bundle(force_refresh=True)

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
            "csrf_token": get_csrf_token(),
            "policy_state": get_policy_state(settings),
            "profile_labels": {
                "stable": "???",
                "balanced": "???",
                "growth": "???",
                "auto": "?????",
            },
            "risk_labels": {
                "low": "??",
                "medium": "??",
                "high": "??",
                "adaptive": "???",
            },
            "regime_labels": {
                "bull": "??",
                "bear": "??",
                "neutral": "??",
                "mixed": "??",
            },
            "change_type_labels": {
                "rebalanced": "????",
                "increase": "?? ??",
                "decrease": "?? ??",
                "hold": "??",
            },
        }

    @app.after_request
    def apply_admin_headers(response: Response) -> Response:
        if request.path.startswith("/admin"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.template_filter("fmt_datetime")
    def fmt_datetime(value: str | None) -> str:
        return _format_datetime(value)

    @app.template_filter("fmt_percent")
    def fmt_percent(value: float | int | None) -> str:
        return _format_percent(value)

    @app.get("/api/v1/user-models")
    def api_user_models() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.user_models), 200)

    @app.get("/api/v1/recommendation/today")
    def api_recommendation_today() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.recommendation_today), 200)

    @app.get("/api/v1/recommendation/<service_profile>")
    def api_recommendation_by_profile(service_profile: str) -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        report_payload = user_snapshot_api.get_recommendation_by_profile(service_profile)
        if report_payload is None:
            return ({"status": "not_found", "message": "service profile not found"}, 404)
        return (jsonify(report_payload), 200)

    @app.get("/api/v1/performance/summary")
    def api_performance_summary() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.performance_summary), 200)

    @app.get("/api/v1/changes/recent")
    def api_changes_recent() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.recent_changes), 200)

    @app.get("/api/v1/publish-status")
    def api_publish_status() -> tuple[dict[str, object], int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return ({"status": "error", "message": "snapshot unavailable"}, 503)
        return (jsonify(bundle.publish_status), 200)

    @app.get("/")
    def home() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/", bundle)
        performance_by_profile = {
            row.get("service_profile"): row for row in bundle.performance_summary.get("models", [])
        }
        status_snapshot = user_snapshot_api.get_status(force_refresh=False)
        return Response(
            render_template(
                "home.html",
                page_title="Home",
                bundle=bundle,
                performance_by_profile=performance_by_profile,
                status_snapshot=status_snapshot,
            ),
            mimetype="text/html",
        )

    @app.get("/theme-preview")
    def theme_preview() -> Response:
        record_page_view("/theme-preview")
        return Response(
            render_template("theme_preview.html", page_title="Theme Preview"), mimetype="text/html"
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
            user = access_store.authenticate_local(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
            )
        except LoginValidationError:
            return redirect(url_for("login", status="invalid", next=next_url))

        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(24)
        return redirect(next_url)

    @app.route("/signup", methods=["GET", "POST"])
    def signup() -> Response:
        next_url = _safe_next_url(request.values.get("next") or url_for("today"))
        if request.method == "GET":
            record_page_view("/signup")
            verification_payload = session.get("phone_verification") or {}
            preview_code = ""
            if settings.phone_verification_preview_enabled:
                preview_code = session.get("phone_verification_preview", "")
            return Response(
                render_template(
                    "signup.html",
                    page_title="Sign Up",
                    status=request.args.get("status", ""),
                    next_url=next_url,
                    phone_number=request.args.get(
                        "phone",
                        verification_payload.get("phone_number", ""),
                    ),
                    preview_code=preview_code,
                ),
                mimetype="text/html",
            )

        action = request.form.get("action", "register")
        next_url = _safe_next_url(request.form.get("next"))
        if action == "request_code":
            phone_number = request.form.get("phone_number", "")
            try:
                verification_code = issue_phone_verification(phone_number)
                session["phone_verification_preview"] = verification_code
                status = "code_sent"
            except RegistrationValidationError:
                status = "error"
            return redirect(url_for("signup", status=status, next=next_url, phone=phone_number))

        phone_number = request.form.get("phone_number", "")
        verification_code = request.form.get("verification_code", "")
        if not is_phone_verification_valid(phone_number, verification_code):
            return redirect(
                url_for("signup", status="code_invalid", next=next_url, phone=phone_number)
            )
        if request.form.get("password", "") != request.form.get("password_confirm", ""):
            return redirect(url_for("signup", status="error", next=next_url, phone=phone_number))

        try:
            access_store.register_local_user(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
                phone_number=phone_number,
            )
        except RegistrationValidationError as exc:
            status = "email_exists" if "이미 가입된 이메일" in str(exc) else "error"
            return redirect(url_for("signup", status=status, next=next_url, phone=phone_number))

        clear_phone_verification()
        session.pop("phone_verification_preview", None)
        return redirect(url_for("login", status="signup_success", next=next_url))

    @app.route("/logout", methods=["GET", "POST"])
    def logout() -> Response:
        session.clear()
        return redirect(url_for("login", status="logged_out"))

    @app.get("/me")
    def me() -> tuple[dict[str, object], int]:
        access_context = current_access_context()
        user = access_context.user
        profile = access_store.get_user_profile(user.id) if user else {}
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
                    "auth_provider": profile.get("auth_provider"),
                    "phone_number": profile.get("phone_number"),
                    "phone_verification_status": profile.get("phone_verification_status"),
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
            return (jsonify({"status": "forbidden", "message": "notify sender blocked"}), 403)
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
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/today", bundle)
        reports = bundle.recommendation_today.get("reports", [])
        for report in reports:
            safe_record_event(
                event_name="model_section_view",
                page="/today",
                model_id=report.get("service_profile"),
            )
        return Response(
            render_template(
                "today.html",
                page_title="Today",
                bundle=bundle,
                status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                reports=reports,
            ),
            mimetype="text/html",
        )

    @app.get("/changes")
    def changes() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/changes", bundle)
        return Response(
            render_template(
                "changes.html",
                page_title="Changes",
                bundle=bundle,
                status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                change_rows=bundle.recent_changes.get("changes", []),
            ),
            mimetype="text/html",
        )

    @app.get("/performance")
    def performance() -> Response | tuple[str, int]:
        bundle = load_user_bundle_or_error()
        if bundle is None:
            return render_user_snapshot_error()
        record_page_view("/performance", bundle)
        return Response(
            render_template(
                "performance.html",
                page_title="Performance",
                bundle=bundle,
                status_snapshot=user_snapshot_api.get_status(force_refresh=False),
                performance_rows=bundle.performance_summary.get("models", []),
            ),
            mimetype="text/html",
        )

    @app.get("/feedback")
    def feedback() -> Response:
        record_page_view("/feedback")
        return Response(
            render_template(
                "feedback.html", page_title="Feedback", status=request.args.get("status", "")
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
        except Exception as exc:  # pragma: no cover
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
        return Response(render_template("privacy.html", page_title="Privacy"), mimetype="text/html")

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

    @app.get("/admin")
    def admin_dashboard() -> Response:
        access_context, access_key = require_admin_access()
        status_snapshot = provider.get_status(force_refresh=False)
        metrics_summary = safe_metrics_summary()
        dashboard_summary = access_store.get_dashboard_summary()
        return Response(
            render_template(
                "admin/dashboard.html",
                page_title="Admin Dashboard",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                access_key=access_key,
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                dashboard_summary=dashboard_summary,
                audit_rows=access_store.list_recent_audit_logs(limit=10),
                published_rows=build_published_snapshot_rows()[:10],
                policy_state=get_policy_state(settings),
                access_context=access_context,
            ),
            mimetype="text/html",
        )

    @app.route("/admin/users", methods=["GET", "POST"])
    def admin_users() -> Response:
        access_context, access_key = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "")
            email = request.form.get("email", "")
            try:
                if action == "lock":
                    access_store.set_user_active(email=email, is_active=False)
                    status = "locked"
                elif action == "unlock":
                    access_store.set_user_active(email=email, is_active=True)
                    status = "unlocked"
                else:
                    raise AdminValidationError("지원하지 않는 action 입니다.")
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.users.{action}",
                    target_type="user",
                    target_id=email,
                    payload_summary={"email": email},
                    result="success",
                )
            except AdminValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.users.{action or 'unknown'}",
                    target_type="user",
                    target_id=email or None,
                    payload_summary={"email": email},
                    result="error",
                )
            params = {"status": status}
            if access_key:
                params["access_key"] = access_key
            return redirect(f"{url_for('admin_users')}?{urlencode(params)}")

        query = request.args.get("q", "")
        return Response(
            render_template(
                "admin/users.html",
                page_title="Admin Users",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                access_key=access_key,
                status=request.args.get("status", ""),
                query=query,
                user_rows=access_store.list_users(query=query, limit=100),
            ),
            mimetype="text/html",
        )

    @app.route("/admin/grant", methods=["GET", "POST"])
    def admin_grant() -> Response:
        access_context, access_key = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "grant")
            email = request.form.get("email", "")
            try:
                if action == "revoke":
                    access_store.revoke_plan(email=email)
                    status = "revoked"
                else:
                    access_store.grant_plan(
                        email=email,
                        plan_id=request.form.get("plan_id", "free"),
                        expires_at=request.form.get("expires_at", "").strip() or None,
                    )
                    status = "granted"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.grant.{action}",
                    target_type="subscription",
                    target_id=email,
                    payload_summary={
                        "email": email,
                        "plan_id": request.form.get("plan_id", "free"),
                        "expires_at": request.form.get("expires_at", ""),
                    },
                    result="success",
                )
            except GrantValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.grant.{action}",
                    target_type="subscription",
                    target_id=email or None,
                    payload_summary={
                        "email": email,
                        "plan_id": request.form.get("plan_id", "free"),
                    },
                    result="error",
                )
            params = {"status": status}
            if access_key:
                params["access_key"] = access_key
            return redirect(f"{url_for('admin_grant')}?{urlencode(params)}")

        return Response(
            render_template(
                "admin/grant.html",
                page_title="Admin Grant",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                status=request.args.get("status", ""),
                plan_rows=access_store.list_plans(),
                access_key=access_key,
            ),
            mimetype="text/html",
        )

    @app.route("/admin/plans-entitlements", methods=["GET", "POST"])
    def admin_plans_entitlements() -> Response:
        access_context, access_key = require_admin_access()
        if request.method == "POST":
            require_csrf()
            try:
                updated = access_store.update_plan_entitlement(
                    plan_id=request.form.get("plan_id", ""),
                    entitlement_key=request.form.get("entitlement_key", ""),
                    value_json=request.form.get("value_json", ""),
                )
                provider.load_bundle(force_refresh=True)
                status = "updated"
                audit_admin(
                    access_context=access_context,
                    action_type="admin.entitlements.update",
                    target_type="plan_entitlement",
                    target_id=f"{updated['plan_id']}:{updated['entitlement_key']}",
                    payload_summary=updated,
                    result="success",
                )
            except AdminValidationError:
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type="admin.entitlements.update",
                    target_type="plan_entitlement",
                    target_id=None,
                    payload_summary={
                        "plan_id": request.form.get("plan_id", ""),
                        "entitlement_key": request.form.get("entitlement_key", ""),
                    },
                    result="error",
                )
            params = {"status": status}
            if access_key:
                params["access_key"] = access_key
            return redirect(f"{url_for('admin_plans_entitlements')}?{urlencode(params)}")

        return Response(
            render_template(
                "admin/plans_entitlements.html",
                page_title="Plans & Entitlements",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                access_key=access_key,
                status=request.args.get("status", ""),
                plan_rows=access_store.list_plans(),
                entitlement_rows=access_store.list_plan_entitlement_rows(),
            ),
            mimetype="text/html",
        )

    @app.route("/admin/publish-snapshots", methods=["GET", "POST"])
    def admin_publish_snapshots() -> Response:
        access_context, access_key = require_admin_access()
        if request.method == "POST":
            require_csrf()
            action = request.form.get("action", "refresh")
            try:
                if action == "activate":
                    label = request.form.get("snapshot_label", "")
                    activate_snapshot_label(label)
                    status = "activated"
                    audit_admin(
                        access_context=access_context,
                        action_type="admin.snapshots.activate",
                        target_type="snapshot",
                        target_id=label,
                        payload_summary={"snapshot_label": label},
                        result="success",
                    )
                else:
                    provider.load_bundle(force_refresh=True)
                    status = "refreshed"
                    audit_admin(
                        access_context=access_context,
                        action_type="admin.snapshots.refresh",
                        target_type="cache",
                        target_id="current",
                        payload_summary={"refresh": True},
                        result="success",
                    )
            except (AdminValidationError, SnapshotLoadError):
                status = "error"
                audit_admin(
                    access_context=access_context,
                    action_type=f"admin.snapshots.{action}",
                    target_type="snapshot",
                    target_id=request.form.get("snapshot_label") or None,
                    payload_summary={"snapshot_label": request.form.get("snapshot_label", "")},
                    result="error",
                )
            params = {"status": status}
            if access_key:
                params["access_key"] = access_key
            return redirect(f"{url_for('admin_publish_snapshots')}?{urlencode(params)}")

        return Response(
            render_template(
                "admin/publish_snapshots.html",
                page_title="Publish & Snapshots",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                access_key=access_key,
                status=request.args.get("status", ""),
                status_snapshot=provider.get_status(force_refresh=False),
                published_rows=build_published_snapshot_rows(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/feedback")
    def admin_feedback() -> Response:
        _, access_key = require_admin_access()
        feedback_rows = safe_list_recent_feedback(limit=100)
        metrics_summary = safe_metrics_summary()
        return Response(
            render_template(
                "admin/feedback.html",
                page_title="Admin Feedback",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                feedback_rows=feedback_rows,
                metrics_summary=metrics_summary,
            ),
            mimetype="text/html",
        )

    @app.get("/admin/metrics")
    def admin_metrics() -> Response:
        _, access_key = require_admin_access()
        return Response(
            render_template(
                "admin/metrics.html",
                page_title="Admin Metrics",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                metrics_summary=safe_metrics_summary(),
                dashboard_summary=access_store.get_dashboard_summary(),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/audit")
    def admin_audit() -> Response:
        _, access_key = require_admin_access()
        return Response(
            render_template(
                "admin/audit.html",
                page_title="Admin Audit",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                audit_rows=access_store.list_recent_audit_logs(limit=200),
            ),
            mimetype="text/html",
        )

    @app.get("/admin/billing")
    def admin_billing() -> Response:
        _, access_key = require_admin_access()
        ensure_billing_enabled()
        return Response(
            render_template(
                "admin/billing.html",
                page_title="Admin Billing",
                page_robots="noindex, nofollow",
                admin_links=build_admin_links(access_key),
                order_rows=access_store.list_recent_orders(limit=100),
                payment_event_rows=access_store.list_recent_payment_events(limit=100),
                subscription_rows=access_store.list_recent_subscriptions(limit=100),
            ),
            mimetype="text/html",
        )

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
                page_title="Status",
                status_snapshot=status_snapshot,
                metrics_summary=metrics_summary,
                publish_status_payload=publish_status_payload,
            ),
            mimetype="text/html",
        )

    @app.get("/healthz")
    @app.get("/health")
    def healthz() -> tuple[dict[str, object], int]:
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
                }
            ),
            200,
        )

    return app


app = create_app()


if __name__ == "__main__":
    current_settings = app.config["SETTINGS"]
    app.run(host=current_settings.web_host, port=current_settings.web_port)
