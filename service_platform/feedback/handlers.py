"""Feedback input helpers and admin access checks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from flask import Request

from service_platform.feedback.storage import FeedbackSubmission
from service_platform.shared.config import Settings


def build_feedback_submission(request: Request) -> FeedbackSubmission:
    return FeedbackSubmission(
        email=request.form.get("email", ""),
        message=request.form.get("message", ""),
        page=request.form.get("page", request.path),
        consent=request.form.get("consent") == "on",
        user_agent=request.headers.get("User-Agent", ""),
        ip_address=_get_client_ip(request),
    )


def is_admin_request(
    request: Request,
    settings: Settings,
    access_context: Any | None = None,
) -> bool:
    if access_context is not None and getattr(access_context, "is_admin", False):
        return True
    if not settings.feedback_admin_key:
        return False
    header_key = request.headers.get("X-Admin-Key", "")
    query_key = request.args.get("access_key", "")
    provided = header_key or query_key
    return provided == settings.feedback_admin_key


def build_feedback_redirect(base_path: str, *, status: str) -> str:
    return f"{base_path}?{urlencode({'status': status})}"


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"
