"""Minimal Flask application entry point for local environment validation."""

from __future__ import annotations

from flask import Flask, jsonify

from service_platform.shared.config import get_settings
from service_platform.shared.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = Flask(__name__)


@app.get("/")
def home() -> tuple[dict[str, str], int]:
    return (
        jsonify(
            {
                "service": "quantservice-web",
                "status": "ok",
                "app_env": settings.app_env,
            }
        ),
        200,
    )


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return jsonify({"status": "ok", "app_env": settings.app_env}), 200


if __name__ == "__main__":
    app.run(host=settings.web_host, port=settings.web_port)
