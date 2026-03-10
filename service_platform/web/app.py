from __future__ import annotations

from flask import Flask, Response, jsonify

from service_platform.shared.config import get_settings
from service_platform.shared.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = Flask(__name__)


@app.get("/")
def home() -> Response:
    return Response(
        """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>QuantService</title>
          <style>
            :root {
              color-scheme: light;
              --bg: #f4efe7;
              --ink: #1d1a16;
              --accent: #b42318;
              --card: #fffaf4;
              --line: #e7d8c7;
            }
            * { box-sizing: border-box; }
            body {
              margin: 0;
              min-height: 100vh;
              display: grid;
              place-items: center;
              background:
                radial-gradient(circle at top, rgba(180, 35, 24, 0.10), transparent 30%),
                linear-gradient(180deg, var(--bg), #efe5d7);
              color: var(--ink);
              font-family: Georgia, "Times New Roman", serif;
            }
            main {
              width: min(92vw, 760px);
              padding: 48px 32px;
              border: 1px solid var(--line);
              border-radius: 24px;
              background: var(--card);
              box-shadow: 0 24px 80px rgba(37, 24, 14, 0.12);
              text-align: center;
            }
            .eyebrow {
              margin: 0 0 14px;
              color: var(--accent);
              font-size: 12px;
              font-weight: 700;
              letter-spacing: 0.24em;
              text-transform: uppercase;
            }
            h1 {
              margin: 0;
              font-size: clamp(40px, 9vw, 76px);
              line-height: 0.95;
            }
            p {
              margin: 18px auto 0;
              max-width: 520px;
              font-size: 18px;
              line-height: 1.7;
            }
            .status {
              display: inline-block;
              margin-top: 28px;
              padding: 10px 16px;
              border-radius: 999px;
              background: rgba(180, 35, 24, 0.08);
              color: var(--accent);
              font-size: 14px;
              font-weight: 700;
            }
          </style>
        </head>
        <body>
          <main>
            <p class="eyebrow">QuantService</p>
            <h1>Under Construction</h1>
            <p>
              A stock recommendation service for Korean investors is currently being prepared.
              We will be back soon with daily model snapshots and clearer market insights.
            </p>
            <div class="status">Service status: preparing launch</div>
          </main>
        </body>
        </html>
        """,
        mimetype="text/html",
    )


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return jsonify({"status": "ok", "app_env": settings.app_env}), 200


if __name__ == "__main__":
    app.run(host=settings.web_host, port=settings.web_port)
