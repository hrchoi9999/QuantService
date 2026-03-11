"""SQLite-backed feedback and lightweight analytics storage."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from service_platform.shared.config import Settings

SEOUL = timezone(timedelta(hours=9))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FeedbackValidationError(ValueError):
    pass


class FeedbackRateLimitError(RuntimeError):
    pass


class FeedbackDuplicateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedbackSubmission:
    email: str
    message: str
    page: str
    consent: bool
    user_agent: str
    ip_address: str


class FeedbackStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.feedback_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    email TEXT NOT NULL,
                    email_hash TEXT,
                    message TEXT NOT NULL,
                    message_hash TEXT NOT NULL,
                    page TEXT NOT NULL,
                    user_agent TEXT,
                    ip_hash TEXT NOT NULL,
                    consent INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    page TEXT,
                    model_id TEXT,
                    ticker TEXT,
                    meta_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_feedback_ip_hash ON feedback(ip_hash);
                CREATE INDEX IF NOT EXISTS idx_feedback_message_hash ON feedback(message_hash);
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);
                """
            )

    def submit_feedback(self, submission: FeedbackSubmission) -> dict[str, str]:
        normalized_email = submission.email.strip().lower()
        normalized_message = submission.message.strip()
        if not submission.consent:
            raise FeedbackValidationError("개인정보 수집·이용 동의가 필요합니다.")
        if len(normalized_message) < self.settings.feedback_message_min_length:
            raise FeedbackValidationError(
                f"의견은 최소 {self.settings.feedback_message_min_length}자 이상 입력해 주세요."
            )
        if normalized_email and not EMAIL_RE.match(normalized_email):
            raise FeedbackValidationError("이메일 형식을 다시 확인해 주세요.")

        created_at = self._now_iso()
        ip_hash = self._hash_text(submission.ip_address or "unknown")
        message_hash = self._hash_text(normalized_message)
        email_hash = self._hash_text(normalized_email) if normalized_email else ""

        with self._connect() as connection:
            self._enforce_rate_limit(connection, ip_hash)
            self._enforce_duplicate_limit(connection, email_hash, message_hash)
            cursor = connection.execute(
                """
                INSERT INTO feedback(
                    created_at,
                    email,
                    email_hash,
                    message,
                    message_hash,
                    page,
                    user_agent,
                    ip_hash,
                    consent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    normalized_email,
                    email_hash,
                    normalized_message,
                    message_hash,
                    submission.page,
                    submission.user_agent[:255],
                    ip_hash,
                    1,
                ),
            )
            feedback_id = str(cursor.lastrowid)

        self.record_event(
            event_name="feedback_submit",
            page=submission.page,
            meta={"feedback_id": feedback_id},
        )
        return {"feedback_id": feedback_id, "created_at": created_at}

    def record_event(
        self,
        *,
        event_name: str,
        page: str | None = None,
        model_id: str | None = None,
        ticker: str | None = None,
        meta: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(created_at, event_name, page, model_id, ticker, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self._now_iso(),
                    event_name,
                    page,
                    model_id,
                    ticker,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )

    def list_recent_feedback(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, email, message, page, user_agent, consent
                FROM feedback
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_metrics_summary(self, window_hours: int | None = None) -> dict:
        window_hours = window_hours or self.settings.analytics_window_hours
        since = (datetime.now(SEOUL) - timedelta(hours=window_hours)).isoformat()
        with self._connect() as connection:
            page_views = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_name = 'page_view' AND created_at >= ?",
                (since,),
            ).fetchone()[0]
            today_views = connection.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE event_name = 'page_view' AND page = '/today' AND created_at >= ?
                """,
                (since,),
            ).fetchone()[0]
            feedback_count = connection.execute(
                "SELECT COUNT(*) FROM feedback WHERE created_at >= ?",
                (since,),
            ).fetchone()[0]
            click_rows = connection.execute(
                """
                SELECT ticker, COUNT(*) AS count
                FROM events
                WHERE event_name = 'ticker_click' AND created_at >= ?
                GROUP BY ticker
                ORDER BY count DESC, ticker ASC
                LIMIT 10
                """,
                (since,),
            ).fetchall()
            model_rows = connection.execute(
                """
                SELECT model_id, COUNT(*) AS count
                FROM events
                WHERE event_name = 'model_section_view' AND created_at >= ?
                GROUP BY model_id
                ORDER BY count DESC, model_id ASC
                LIMIT 10
                """,
                (since,),
            ).fetchall()

        return {
            "window_hours": window_hours,
            "page_views": page_views,
            "today_page_views": today_views,
            "feedback_submissions": feedback_count,
            "ticker_clicks": [dict(row) for row in click_rows],
            "model_interest": [dict(row) for row in model_rows],
        }

    def _enforce_rate_limit(self, connection: sqlite3.Connection, ip_hash: str) -> None:
        since = (
            datetime.now(SEOUL) - timedelta(seconds=self.settings.feedback_rate_limit_seconds)
        ).isoformat()
        row = connection.execute(
            "SELECT 1 FROM feedback WHERE ip_hash = ? AND created_at >= ? LIMIT 1",
            (ip_hash, since),
        ).fetchone()
        if row:
            raise FeedbackRateLimitError("잠시 후 다시 제출해 주세요.")

    def _enforce_duplicate_limit(
        self,
        connection: sqlite3.Connection,
        email_hash: str,
        message_hash: str,
    ) -> None:
        since = (
            datetime.now(SEOUL) - timedelta(seconds=self.settings.feedback_duplicate_window_seconds)
        ).isoformat()
        row = connection.execute(
            """
            SELECT 1
            FROM feedback
            WHERE message_hash = ? AND created_at >= ?
              AND (? = '' OR email_hash = ?)
            LIMIT 1
            """,
            (message_hash, since, email_hash, email_hash),
        ).fetchone()
        if row:
            raise FeedbackDuplicateError("같은 내용의 의견이 최근에 접수되었습니다.")

    def _now_iso(self) -> str:
        return datetime.now(SEOUL).isoformat()

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
