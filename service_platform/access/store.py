from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from service_platform.shared.config import Settings

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\d{10,11}$")
PLAN_PRIORITY = {"free": 0, "starter": 1, "pro": 2, "premium": 3}
PLAN_SEEDS = [
    ("free", "Free", "Preview only", 1),
    ("starter", "Starter", "Trial tier / top 10 per model", 1),
    ("pro", "Pro", "Top 20 per model", 1),
    ("premium", "Premium", "Top 30 per model", 1),
]
ENTITLEMENT_SEEDS = [
    ("models_enabled", "Allowed model identifiers", "list"),
    ("recommendation_sort_order", "Recommendation sort order", "json"),
    ("recommendation_n_per_model", "Recommendation count per model", "int"),
    ("view_history_days", "Historical performance window", "int"),
    ("view_changes_days", "Recent changes window", "int"),
    ("export_csv", "CSV export availability", "bool"),
    ("admin_access", "Administrative grant access", "bool"),
]
PLAN_ENTITLEMENT_SEEDS = {
    "free": {
        "models_enabled": ["*"],
        "recommendation_sort_order": "bottom",
        "recommendation_n_per_model": 3,
        "view_history_days": 30,
        "view_changes_days": 7,
        "export_csv": False,
        "admin_access": False,
    },
    "starter": {
        "models_enabled": ["*"],
        "recommendation_sort_order": "top",
        "recommendation_n_per_model": 10,
        "view_history_days": 90,
        "view_changes_days": 14,
        "export_csv": False,
        "admin_access": False,
    },
    "pro": {
        "models_enabled": ["*"],
        "recommendation_sort_order": "top",
        "recommendation_n_per_model": 20,
        "view_history_days": 180,
        "view_changes_days": 30,
        "export_csv": True,
        "admin_access": False,
    },
    "premium": {
        "models_enabled": ["*"],
        "recommendation_sort_order": "top",
        "recommendation_n_per_model": 30,
        "view_history_days": 365,
        "view_changes_days": 60,
        "export_csv": True,
        "admin_access": False,
    },
}
PLAN_ORDER_SQL = """
SELECT plan_id, name, pricing_hint, is_active
FROM plans
ORDER BY CASE plan_id
    WHEN 'free' THEN 1
    WHEN 'starter' THEN 2
    WHEN 'pro' THEN 3
    WHEN 'premium' THEN 4
    ELSE 99
END
"""


class LoginValidationError(ValueError):
    pass


class RegistrationValidationError(ValueError):
    pass


class GrantValidationError(ValueError):
    pass


class AdminValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UserRecord:
    id: int
    email: str
    is_active: bool
    created_at: str
    last_login_at: str | None


@dataclass(frozen=True)
class AccessContext:
    authenticated: bool
    user: UserRecord | None
    roles: tuple[str, ...]
    base_plan_id: str
    effective_plan_id: str
    entitlements: dict[str, Any]
    trial_active: bool
    trial_end_date: str | None
    is_admin: bool


class AccessStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.app_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._seed_defaults()

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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    auth_provider TEXT NOT NULL DEFAULT 'local',
                    display_name TEXT,
                    phone_number TEXT,
                    phone_verification_status TEXT NOT NULL DEFAULT 'unverified',
                    phone_verified_at TEXT,
                    external_subject TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pricing_hint TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    expires_at TEXT,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS entitlements (
                    key TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    value_type TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plan_entitlements (
                    plan_id TEXT NOT NULL,
                    entitlement_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    PRIMARY KEY(plan_id, entitlement_key)
                );

                CREATE TABLE IF NOT EXISTS roles (
                    role_id TEXT PRIMARY KEY,
                    description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id INTEGER NOT NULL,
                    role_id TEXT NOT NULL,
                    PRIMARY KEY(user_id, role_id),
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(role_id) REFERENCES roles(role_id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    ord_no TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    plan_id TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    pay_method_requested TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS payment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    tid TEXT,
                    ord_no TEXT NOT NULL,
                    mid TEXT,
                    result_cd TEXT,
                    result_msg TEXT,
                    pm_cd TEXT,
                    spm_cd TEXT,
                    goods_amt TEXT,
                    edi_date TEXT,
                    raw_payload TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_user_id INTEGER,
                    action_type TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    payload_summary TEXT NOT NULL,
                    result TEXT NOT NULL,
                    ip_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(admin_user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
                CREATE INDEX IF NOT EXISTS idx_user_profiles_phone ON user_profiles(phone_number);
                CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status
                ON subscriptions(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);
                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
                CREATE INDEX IF NOT EXISTS idx_payment_events_ord_no ON payment_events(ord_no);
                CREATE INDEX IF NOT EXISTS idx_payment_events_tid ON payment_events(tid);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_logs_admin_user_id
                ON audit_logs(admin_user_id);
                """
            )

    def _seed_defaults(self) -> None:
        created_at = self._now_iso()
        with self._connect() as connection:
            plan_rows = [
                (plan_id, name, pricing_hint, is_active, created_at)
                for plan_id, name, pricing_hint, is_active in PLAN_SEEDS
            ]
            connection.executemany(
                """
                INSERT OR IGNORE INTO plans(plan_id, name, pricing_hint, is_active, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                plan_rows,
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO entitlements(key, description, value_type)
                VALUES (?, ?, ?)
                """,
                ENTITLEMENT_SEEDS,
            )
            connection.execute(
                "INSERT OR IGNORE INTO roles(role_id, description) VALUES ('admin', ?)",
                ("Administrative access",),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO user_profiles(
                    user_id,
                    auth_provider,
                    phone_verification_status,
                    phone_verified_at,
                    created_at,
                    updated_at
                )
                SELECT id, 'local', 'verified', created_at, created_at, created_at
                FROM users
                """
            )
            for plan_id, entitlement_map in PLAN_ENTITLEMENT_SEEDS.items():
                for entitlement_key, value in entitlement_map.items():
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO plan_entitlements(
                            plan_id, entitlement_key, value_json
                        )
                        VALUES (?, ?, ?)
                        """,
                        (plan_id, entitlement_key, json.dumps(value, ensure_ascii=False)),
                    )

    def authenticate_or_register(self, email: str, password: str) -> UserRecord:
        normalized_email = self._normalize_email(email)
        normalized_password = password.strip()
        if not EMAIL_RE.match(normalized_email):
            raise LoginValidationError("이메일 형식을 확인해 주세요.")
        if len(normalized_password) < 4:
            raise LoginValidationError("비밀번호는 최소 4자 이상 입력해 주세요.")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ? LIMIT 1",
                (normalized_email,),
            ).fetchone()
            now = self._now_iso()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO users(email, password_hash, created_at, last_login_at, is_active)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (normalized_email, generate_password_hash(normalized_password), now, now),
                )
                return UserRecord(
                    id=int(cursor.lastrowid),
                    email=normalized_email,
                    is_active=True,
                    created_at=now,
                    last_login_at=now,
                )

            if not row["is_active"]:
                raise LoginValidationError("비활성화된 계정입니다.")

            stored_hash = row["password_hash"] or ""
            if not stored_hash:
                connection.execute(
                    "UPDATE users SET password_hash = ?, last_login_at = ? WHERE id = ?",
                    (generate_password_hash(normalized_password), now, row["id"]),
                )
                return UserRecord(
                    id=row["id"],
                    email=row["email"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                    last_login_at=now,
                )

            if not check_password_hash(stored_hash, normalized_password):
                raise LoginValidationError("이메일 또는 비밀번호를 다시 확인해 주세요.")

            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            return UserRecord(
                id=row["id"],
                email=row["email"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                last_login_at=now,
            )

    def get_user_by_id(self, user_id: int | None) -> UserRecord | None:
        if user_id is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, is_active, created_at, last_login_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            id=row["id"],
            email=row["email"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    def get_user_by_email(self, email: str) -> UserRecord | None:
        normalized_email = self._normalize_email(email)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE email = ? LIMIT 1",
                (normalized_email,),
            ).fetchone()
        if row is None:
            return None
        return self.get_user_by_id(row["id"])

    def get_user_profile(self, user_id: int) -> dict[str, Any]:
        self._ensure_user_profile(user_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT auth_provider, display_name, phone_number,
                       phone_verification_status, phone_verified_at, external_subject
                FROM user_profiles
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def authenticate_local(self, email: str, password: str) -> UserRecord:
        normalized_email = self._normalize_email(email)
        normalized_password = password.strip()
        if not EMAIL_RE.match(normalized_email):
            raise LoginValidationError("이메일 형식을 확인해 주세요.")
        if len(normalized_password) < 4:
            raise LoginValidationError("비밀번호를 다시 확인해 주세요.")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ? LIMIT 1",
                (normalized_email,),
            ).fetchone()
            now = self._now_iso()
            if row is None:
                raise LoginValidationError(
                    "가입된 계정을 찾지 못했습니다. 먼저 회원가입을 진행해 주세요."
                )
            if not row["is_active"]:
                raise LoginValidationError("비활성화된 계정입니다.")
            stored_hash = row["password_hash"] or ""
            if not stored_hash or not check_password_hash(stored_hash, normalized_password):
                raise LoginValidationError("이메일 또는 비밀번호를 다시 확인해 주세요.")
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        return UserRecord(
            id=row["id"],
            email=row["email"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            last_login_at=now,
        )

    def register_local_user(
        self,
        *,
        email: str,
        password: str,
        phone_number: str,
        display_name: str | None = None,
    ) -> UserRecord:
        normalized_email = self._normalize_email(email)
        normalized_password = password.strip()
        normalized_phone = self._normalize_phone_number(phone_number)
        if not EMAIL_RE.match(normalized_email):
            raise RegistrationValidationError("이메일 형식을 확인해 주세요.")
        if len(normalized_password) < 8:
            raise RegistrationValidationError("비밀번호는 8자 이상 입력해 주세요.")
        if self.get_user_by_email(normalized_email) is not None:
            raise RegistrationValidationError("이미 가입된 이메일입니다. 로그인해 주세요.")

        now = self._now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(email, password_hash, created_at, last_login_at, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (normalized_email, generate_password_hash(normalized_password), now, now),
            )
            user_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT OR REPLACE INTO user_profiles(
                    user_id,
                    auth_provider,
                    display_name,
                    phone_number,
                    phone_verification_status,
                    phone_verified_at,
                    external_subject,
                    created_at,
                    updated_at
                )
                VALUES (?, 'local', ?, ?, 'verified', ?, NULL, ?, ?)
                """,
                (
                    user_id,
                    (display_name or normalized_email.split("@")[0])[:80],
                    normalized_phone,
                    now,
                    now,
                    now,
                ),
            )
        return UserRecord(
            id=user_id,
            email=normalized_email,
            is_active=True,
            created_at=now,
            last_login_at=now,
        )

    def list_users(self, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        normalized_query = query.strip().lower()
        sql = (
            "SELECT id, email, is_active, created_at, last_login_at FROM users "
            "WHERE (? = '' OR lower(email) LIKE ?) "
            "ORDER BY created_at DESC LIMIT ?"
        )
        like_query = f"%{normalized_query}%"
        with self._connect() as connection:
            rows = connection.execute(sql, (normalized_query, like_query, limit)).fetchall()
        users: list[dict[str, Any]] = []
        for row in rows:
            user = UserRecord(
                id=row["id"],
                email=row["email"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                last_login_at=row["last_login_at"],
            )
            access = self.get_effective_access(user.id)
            profile = self.get_user_profile(user.id)
            users.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "is_active": user.is_active,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "roles": list(access.roles),
                    "base_plan_id": access.base_plan_id,
                    "effective_plan_id": access.effective_plan_id,
                    "trial_active": access.trial_active,
                    "subscription_status": self.get_subscription_summary(user.id),
                    "auth_provider": profile.get("auth_provider", "local"),
                    "phone_number": profile.get("phone_number"),
                    "phone_verification_status": profile.get(
                        "phone_verification_status", "unverified"
                    ),
                }
            )
        return users

    def set_user_active(self, *, email: str, is_active: bool) -> dict[str, Any]:
        user = self._ensure_user(email)
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, user.id),
            )
        return {"email": user.email, "is_active": is_active}

    def list_plans(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(PLAN_ORDER_SQL).fetchall()
        return [dict(row) for row in rows]

    def list_entitlements(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, description, value_type FROM entitlements ORDER BY key ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_plan_entitlement_rows(self) -> list[dict[str, Any]]:
        entitlement_defs = {row["key"]: row for row in self.list_entitlements()}
        rows: list[dict[str, Any]] = []
        for plan in self.list_plans():
            values = self.get_plan_entitlements(plan["plan_id"])
            for entitlement_key, value in values.items():
                definition = entitlement_defs.get(entitlement_key, {})
                rows.append(
                    {
                        "plan_id": plan["plan_id"],
                        "entitlement_key": entitlement_key,
                        "value": value,
                        "value_json": json.dumps(value, ensure_ascii=False),
                        "value_type": definition.get("value_type", "json"),
                        "description": definition.get("description", ""),
                    }
                )
        return rows

    def update_plan_entitlement(
        self,
        *,
        plan_id: str,
        entitlement_key: str,
        value_json: str,
    ) -> dict[str, Any]:
        normalized_plan = plan_id.strip().lower()
        normalized_key = entitlement_key.strip()
        if normalized_plan not in PLAN_PRIORITY:
            raise AdminValidationError("지원하지 않는 plan_id 입니다.")
        entitlement_defs = {row["key"]: row for row in self.list_entitlements()}
        if normalized_key not in entitlement_defs:
            raise AdminValidationError("지원하지 않는 entitlement_key 입니다.")
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError as exc:
            raise AdminValidationError("entitlement 값은 JSON 형식이어야 합니다.") from exc
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO plan_entitlements(
                            plan_id, entitlement_key, value_json
                        )
                VALUES (?, ?, ?)
                """,
                (normalized_plan, normalized_key, json.dumps(value, ensure_ascii=False)),
            )
        return {
            "plan_id": normalized_plan,
            "entitlement_key": normalized_key,
            "value": value,
        }

    def get_effective_access(
        self,
        user_id: int | None,
        today: date | None = None,
    ) -> AccessContext:
        user = self.get_user_by_id(user_id)
        if user is None or not user.is_active:
            return self._build_access_context(None, (), "free", "free", today)

        roles = self.get_roles(user.id)
        base_plan_id = self._get_base_plan_id(user.id)
        effective_plan_id = self._resolve_effective_plan(base_plan_id, today=today)
        return self._build_access_context(
            user,
            roles,
            base_plan_id,
            effective_plan_id,
            today,
        )

    def grant_plan(
        self,
        *,
        email: str,
        plan_id: str,
        expires_at: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        normalized_plan = plan_id.strip().lower()
        if normalized_plan not in PLAN_PRIORITY:
            raise GrantValidationError("지원하지 않는 plan_id 입니다.")
        if expires_at:
            self._parse_date(expires_at)

        user = self._ensure_user(email)
        now = self._now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE subscriptions
                SET status = 'canceled', updated_at = ?
                WHERE user_id = ? AND status IN ('active', 'trial')
                """,
                (now, user.id),
            )
            if normalized_plan != "free":
                connection.execute(
                    """
                    INSERT INTO subscriptions(
                        user_id,
                        plan_id,
                        status,
                        started_at,
                        expires_at,
                        source,
                        updated_at
                    )
                    VALUES (?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (user.id, normalized_plan, now, expires_at, source, now),
                )

        return {
            "email": user.email,
            "plan_id": normalized_plan,
            "expires_at": expires_at,
        }

    def revoke_plan(self, *, email: str) -> dict[str, Any]:
        user = self._ensure_user(email)
        now = self._now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE subscriptions
                SET status = 'canceled', updated_at = ?
                WHERE user_id = ? AND status IN ('active', 'trial')
                """,
                (now, user.id),
            )
        return {"email": user.email, "plan_id": "free"}

    def assign_role(self, *, email: str, role_id: str = "admin") -> None:
        if role_id != "admin":
            raise GrantValidationError("지원하지 않는 role_id 입니다.")
        user = self._ensure_user(email)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)",
                (user.id, role_id),
            )

    def create_order(
        self,
        *,
        ord_no: str,
        user_id: int,
        plan_id: str,
        amount: int,
        currency: str,
        pay_method_requested: str,
        status: str = "init",
    ) -> dict[str, Any]:
        now = self._now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO orders(
                    ord_no,
                    user_id,
                    plan_id,
                    amount,
                    currency,
                    pay_method_requested,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ord_no,
                    user_id,
                    plan_id,
                    amount,
                    currency,
                    pay_method_requested,
                    status,
                    now,
                    now,
                ),
            )
        order = self.get_order_by_ord_no(ord_no)
        assert order is not None
        return order

    def get_order_by_ord_no(self, ord_no: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ord_no, user_id, plan_id, amount, currency, pay_method_requested,
                       status, created_at, updated_at
                FROM orders
                WHERE ord_no = ?
                LIMIT 1
                """,
                (ord_no,),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_order_status(self, *, ord_no: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE ord_no = ?",
                (status, self._now_iso(), ord_no),
            )

    def list_orders_for_user(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ord_no, user_id, plan_id, amount, currency, pay_method_requested,
                       status, created_at, updated_at
                FROM orders
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ord_no, user_id, plan_id, amount, currency, pay_method_requested,
                       status, created_at, updated_at
                FROM orders
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_payment_event(
        self,
        *,
        provider: str,
        event_type: str,
        ord_no: str,
        tid: str,
        mid: str,
        result_cd: str,
        result_msg: str,
        pm_cd: str,
        goods_amt: str,
        edi_date: str,
        raw_payload: dict[str, Any],
        idempotency_key: str,
        spm_cd: str = "",
    ) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO payment_events(
                        provider,
                        event_type,
                        tid,
                        ord_no,
                        mid,
                        result_cd,
                        result_msg,
                        pm_cd,
                        spm_cd,
                        goods_amt,
                        edi_date,
                        raw_payload,
                        idempotency_key,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider,
                        event_type,
                        tid,
                        ord_no,
                        mid,
                        result_cd,
                        result_msg,
                        pm_cd,
                        spm_cd,
                        goods_amt,
                        edi_date,
                        json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                        idempotency_key,
                        self._now_iso(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def count_payment_events(self, *, ord_no: str, event_type: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM payment_events WHERE ord_no = ?"
        params: list[Any] = [ord_no]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        with self._connect() as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        return int(row[0]) if row is not None else 0

    def list_recent_payment_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, provider, event_type, tid, ord_no, mid, result_cd,
                       result_msg, pm_cd, spm_cd, goods_amt, edi_date,
                       idempotency_key, created_at
                FROM payment_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def activate_subscription_from_payment(
        self,
        *,
        user_id: int,
        plan_id: str,
        started_at: str,
        expires_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE subscriptions
                SET status = 'canceled', updated_at = ?
                WHERE user_id = ? AND status IN ('active', 'trial')
                """,
                (started_at, user_id),
            )
            connection.execute(
                """
                INSERT INTO subscriptions(
                    user_id,
                    plan_id,
                    status,
                    started_at,
                    expires_at,
                    source,
                    updated_at
                )
                VALUES (?, ?, 'active', ?, ?, 'billing', ?)
                """,
                (user_id, plan_id, started_at, expires_at, started_at),
            )

    def list_recent_subscriptions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT subscriptions.id, subscriptions.user_id, users.email, subscriptions.plan_id,
                       subscriptions.status, subscriptions.started_at, subscriptions.expires_at,
                       subscriptions.source, subscriptions.updated_at
                FROM subscriptions
                JOIN users ON users.id = subscriptions.user_id
                ORDER BY subscriptions.updated_at DESC, subscriptions.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_roles(self, user_id: int) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role_id FROM user_roles WHERE user_id = ? ORDER BY role_id ASC",
                (user_id,),
            ).fetchall()
        return tuple(row["role_id"] for row in rows)

    def get_plan_entitlements(self, plan_id: str) -> dict[str, Any]:
        normalized_plan = plan_id.strip().lower()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT entitlement_key, value_json FROM plan_entitlements WHERE plan_id = ?",
                (normalized_plan,),
            ).fetchall()
        if not rows:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT entitlement_key, value_json
                    FROM plan_entitlements
                    WHERE plan_id = 'free'
                    """
                ).fetchall()
        return {row["entitlement_key"]: json.loads(row["value_json"]) for row in rows}

    def list_recent_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT audit_logs.id, audit_logs.admin_user_id, users.email AS admin_email,
                       audit_logs.action_type, audit_logs.target_type, audit_logs.target_id,
                       audit_logs.payload_summary, audit_logs.result, audit_logs.created_at
                FROM audit_logs
                LEFT JOIN users ON users.id = audit_logs.admin_user_id
                ORDER BY audit_logs.created_at DESC, audit_logs.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_audit_log(
        self,
        *,
        admin_user_id: int | None,
        action_type: str,
        target_type: str,
        target_id: str | None,
        payload_summary: str,
        result: str,
        ip_address: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_logs(
                    admin_user_id,
                    action_type,
                    target_type,
                    target_id,
                    payload_summary,
                    result,
                    ip_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin_user_id,
                    action_type,
                    target_type,
                    target_id,
                    payload_summary[:400],
                    result,
                    self._hash_text(ip_address or "unknown"),
                    self._now_iso(),
                ),
            )

    def get_dashboard_summary(self) -> dict[str, Any]:
        now = self._now_iso()
        with self._connect() as connection:
            user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active_user_count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1"
            ).fetchone()[0]
            admin_count = connection.execute(
                "SELECT COUNT(DISTINCT user_id) FROM user_roles WHERE role_id = 'admin'"
            ).fetchone()[0]
            active_subscription_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM subscriptions
                WHERE status IN ('active', 'trial')
                  AND (expires_at IS NULL OR expires_at >= ?)
                """,
                (now,),
            ).fetchone()[0]
            order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            approved_order_count = connection.execute(
                "SELECT COUNT(*) FROM orders WHERE status = 'approved'"
            ).fetchone()[0]
            payment_event_count = connection.execute(
                "SELECT COUNT(*) FROM payment_events"
            ).fetchone()[0]
            latest_audit = connection.execute(
                "SELECT created_at FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return {
            "user_count": int(user_count),
            "active_user_count": int(active_user_count),
            "admin_count": int(admin_count),
            "active_subscription_count": int(active_subscription_count),
            "order_count": int(order_count),
            "approved_order_count": int(approved_order_count),
            "payment_event_count": int(payment_event_count),
            "latest_audit_at": latest_audit["created_at"] if latest_audit else None,
        }

    def get_subscription_summary(self, user_id: int) -> dict[str, Any]:
        now = self._now_iso()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, plan_id, status, started_at, expires_at, source, updated_at
                FROM subscriptions
                WHERE user_id = ?
                  AND status IN ('active', 'trial')
                  AND (expires_at IS NULL OR expires_at >= ?)
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, now),
            ).fetchone()
        return dict(row) if row is not None else {}

    def is_trial_active(self, today: date | None = None) -> bool:
        if not self.settings.trial_mode:
            return False
        if self.settings.trial_applies_to != "authenticated_only":
            return False
        if not self.settings.trial_end_date:
            return True
        comparison_day = today or datetime.now(timezone.utc).date()
        return comparison_day <= self._parse_date(self.settings.trial_end_date)

    def _build_access_context(
        self,
        user: UserRecord | None,
        roles: tuple[str, ...],
        base_plan_id: str,
        effective_plan_id: str,
        today: date | None,
    ) -> AccessContext:
        entitlements = self.get_plan_entitlements(effective_plan_id)
        trial_active = self.is_trial_active(today=today) if user else False
        is_admin = "admin" in roles or bool(entitlements.get("admin_access", False))
        return AccessContext(
            authenticated=user is not None,
            user=user,
            roles=roles,
            base_plan_id=base_plan_id,
            effective_plan_id=effective_plan_id,
            entitlements=entitlements,
            trial_active=trial_active,
            trial_end_date=self.settings.trial_end_date or None,
            is_admin=is_admin,
        )

    def _resolve_effective_plan(
        self,
        base_plan_id: str,
        today: date | None = None,
    ) -> str:
        normalized_base = base_plan_id if base_plan_id in PLAN_PRIORITY else "free"
        if not self.is_trial_active(today=today):
            return normalized_base
        trial_plan = self.settings.trial_default_plan
        if trial_plan not in PLAN_PRIORITY:
            trial_plan = "starter"
        if not self.settings.allow_higher_plan_during_trial:
            return trial_plan
        return max(normalized_base, trial_plan, key=lambda item: PLAN_PRIORITY[item])

    def _get_base_plan_id(self, user_id: int) -> str:
        now = self._now_iso()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT plan_id
                FROM subscriptions
                WHERE user_id = ?
                  AND status IN ('active', 'trial')
                  AND (expires_at IS NULL OR expires_at >= ?)
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, now),
            ).fetchone()
        if row is None:
            return "free"
        return row["plan_id"]

    def _ensure_user(self, email: str) -> UserRecord:
        normalized_email = self._normalize_email(email)
        if not EMAIL_RE.match(normalized_email):
            raise GrantValidationError("이메일 형식을 확인해 주세요.")
        existing = self.get_user_by_email(normalized_email)
        if existing is not None:
            return existing

        now = self._now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(email, password_hash, created_at, is_active)
                VALUES (?, '', ?, 1)
                """,
                (normalized_email, now),
            )
            return UserRecord(
                id=int(cursor.lastrowid),
                email=normalized_email,
                is_active=True,
                created_at=now,
                last_login_at=None,
            )

    def _ensure_user_profile(self, user_id: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is not None:
                return
            now = self._now_iso()
            connection.execute(
                """
                INSERT INTO user_profiles(
                    user_id,
                    auth_provider,
                    display_name,
                    phone_number,
                    phone_verification_status,
                    phone_verified_at,
                    external_subject,
                    created_at,
                    updated_at
                )
                VALUES (?, 'local', NULL, NULL, 'unverified', NULL, NULL, ?, ?)
                """,
                (user_id, now, now),
            )

    def _upsert_user_profile(
        self,
        user_id: int,
        *,
        auth_provider: str = "local",
        phone_number: str | None = None,
        verified: bool = False,
        display_name: str | None = None,
        external_subject: str | None = None,
    ) -> None:
        now = self._now_iso()
        with self._connect() as connection:
            row = connection.execute(
                (
                    "SELECT user_id, phone_number, phone_verified_at "
                    "FROM user_profiles WHERE user_id = ?"
                ),
                (user_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO user_profiles(
                        user_id,
                        auth_provider,
                        display_name,
                        phone_number,
                        phone_verification_status,
                        phone_verified_at,
                        external_subject,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        auth_provider,
                        display_name,
                        phone_number,
                        "verified" if verified else "unverified",
                        now if verified else None,
                        external_subject,
                        now,
                        now,
                    ),
                )
                return

            connection.execute(
                """
                UPDATE user_profiles
                SET auth_provider = COALESCE(NULLIF(?, ''), auth_provider),
                    display_name = COALESCE(?, display_name),
                    phone_number = COALESCE(?, phone_number),
                    phone_verification_status = ?,
                    phone_verified_at = COALESCE(phone_verified_at, ?),
                    external_subject = COALESCE(?, external_subject),
                    updated_at = ?
                WHERE user_id = ?
                """,
                (
                    auth_provider,
                    display_name,
                    phone_number,
                    "verified" if verified or row["phone_verified_at"] else "unverified",
                    now if verified else None,
                    external_subject,
                    now,
                    user_id,
                ),
            )

    def _normalize_phone_number(self, phone_number: str) -> str:
        digits_only = "".join(ch for ch in phone_number if ch.isdigit())
        if not PHONE_RE.match(digits_only):
            raise RegistrationValidationError("휴대폰 번호는 숫자 10~11자리로 입력해 주세요.")
        return digits_only

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def _parse_date(self, value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise GrantValidationError("날짜는 YYYY-MM-DD 형식으로 입력해 주세요.") from exc

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_today_sections(
    models: list[dict[str, Any]],
    entitlements: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed_models = entitlements.get("models_enabled", ["*"])
    sort_order = entitlements.get("recommendation_sort_order", "top")
    per_model = int(entitlements.get("recommendation_n_per_model", 3))
    reverse = sort_order != "bottom"
    sections: list[dict[str, Any]] = []

    for model in models:
        model_id = model.get("model_id", "")
        if allowed_models != ["*"] and model_id not in allowed_models:
            continue

        picks = list(model.get("top_picks", []))
        sorted_picks = sorted(
            picks,
            key=lambda item: float(item.get("score") or 0),
            reverse=reverse,
        )
        visible_picks = []
        for index, pick in enumerate(sorted_picks[:per_model], start=1):
            visible_pick = dict(pick)
            visible_pick["rank"] = index
            visible_picks.append(visible_pick)

        sections.append(
            {
                "model_id": model_id,
                "display_picks": visible_picks,
                "available_pick_count": len(picks),
                "display_count": len(visible_picks),
            }
        )

    return sections
