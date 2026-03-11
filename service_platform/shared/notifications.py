"""Alert delivery helpers for ops stability."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib import request

from service_platform.shared.config import Settings

LOGGER = logging.getLogger("quantservice")
_LAST_ALERT_AT: dict[str, float] = {}


def send_alert(
    settings: Settings,
    *,
    title: str,
    message: str,
    alert_key: str,
    force: bool = False,
) -> None:
    now = time.monotonic()
    last_sent = _LAST_ALERT_AT.get(alert_key, 0.0)
    if not force and now - last_sent < settings.alert_throttle_seconds:
        return

    _LAST_ALERT_AT[alert_key] = now
    _write_alert_log(settings.alert_log_path, title=title, message=message, alert_key=alert_key)
    if settings.alert_webhook_url:
        _send_webhook(settings.alert_webhook_url, title=title, message=message)


def _write_alert_log(path: Path, *, title: str, message: str, alert_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"title": title, "message": message, "alert_key": alert_key, "ts": time.time()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _send_webhook(webhook_url: str, *, title: str, message: str) -> None:
    data = json.dumps({"text": f"[{title}] {message}"}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5):
            return
    except Exception as exc:  # pragma: no cover - network optional
        LOGGER.warning("alert webhook failed: %s", exc)
