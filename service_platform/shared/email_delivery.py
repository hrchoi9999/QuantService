"""Email delivery helpers for login verification."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any


class EmailDeliveryError(RuntimeError):
    """Raised when an email cannot be delivered."""


def _build_login_verification_message(
    *,
    from_email: str,
    from_name: str,
    to_email: str,
    code: str,
    ttl_seconds: int,
) -> EmailMessage:
    ttl_minutes = max(1, int(ttl_seconds / 60))
    message = EmailMessage()
    message["Subject"] = "[RedBot] 로그인 인증번호"
    message["From"] = formataddr((from_name or "RedBot", from_email))
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                "RedBot 로그인 인증번호입니다.",
                "",
                f"인증번호: {code}",
                f"유효시간: {ttl_minutes}분",
                "",
                "본인이 요청하지 않았다면 이 메일을 무시해 주세요.",
                "RedBot은 이메일로 비밀번호를 요청하지 않습니다.",
            ]
        )
    )
    return message


def send_login_verification_email(
    *,
    settings: Any,
    to_email: str,
    code: str,
) -> None:
    """Send a login verification email using the configured provider."""

    mode = str(getattr(settings, "login_email_verification_mode", "mock") or "mock").lower()
    if mode == "mock":
        return
    if mode != "smtp":
        raise EmailDeliveryError(f"지원하지 않는 이메일 발송 방식입니다: {mode}")

    host = str(getattr(settings, "login_email_verification_smtp_host", "") or "").strip()
    port = int(getattr(settings, "login_email_verification_smtp_port", 465) or 465)
    username = str(getattr(settings, "login_email_verification_smtp_username", "") or "").strip()
    password = str(getattr(settings, "login_email_verification_smtp_password", "") or "")
    from_email = str(getattr(settings, "login_email_verification_from_email", "") or "").strip()
    from_email = from_email or username
    if not host or not username or not password or not from_email:
        raise EmailDeliveryError("SMTP 이메일 발송 설정이 부족합니다.")

    message = _build_login_verification_message(
        from_email=from_email,
        from_name=str(getattr(settings, "login_email_verification_from_name", "RedBot") or ""),
        to_email=to_email,
        code=code,
        ttl_seconds=int(getattr(settings, "login_email_verification_code_ttl_seconds", 300)),
    )
    timeout = int(getattr(settings, "login_email_verification_smtp_timeout_seconds", 10) or 10)
    use_ssl = bool(getattr(settings, "login_email_verification_smtp_ssl", True))
    use_starttls = bool(getattr(settings, "login_email_verification_smtp_starttls", False))

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                server.login(username, password)
                server.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=timeout) as server:
            if use_starttls:
                server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("이메일 인증번호를 발송하지 못했습니다.") from exc
