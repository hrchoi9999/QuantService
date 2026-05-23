from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from service_platform.access.store import AccessStore
from service_platform.shared.config import Settings

INVESTMENT_ACCOUNT_LABELS = {
    "virtual": "가상투자",
    "live": "실투자",
    "live2": "실투자2",
}
INVESTMENT_SIDE_LABELS = {"buy": "매수", "sell": "매도"}
INVESTMENT_PROFIT_TONES = {"up": "up", "down": "down", "flat": "flat"}
FALLBACK_TRADING_SIGN_DETAIL_PATH = (
    Path(__file__).resolve().parent
    / "public_data"
    / "trading_sign"
    / "current"
    / "tradingsign_model_detail.json"
)
NAVER_QUOTE_URL_TEMPLATE = (
    "https://polling.finance.naver.com/api/realtime?query="
    "SERVICE_ITEM:{ticker}|SERVICE_RECENT_ITEM:{ticker}"
)
QUOTE_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
NAVER_SISE_URL_TEMPLATE = "https://finance.naver.com/item/sise.naver?code={ticker}"
NAVER_SISE_PRICE_PATTERN = re.compile(
    r'class="no_today"[\s\S]*?<span class="blind">([0-9,]+)</span>'
)
NAVER_SISE_TITLE_PATTERN = re.compile(r"<title>\s*([^:<]+)\s*:")
NAVER_DAILY_PRICE_URL_TEMPLATE = (
    "https://finance.naver.com/item/sise_day.naver?code={ticker}&page={page}"
)
NAVER_DAILY_ROW_PATTERN = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
NAVER_DAILY_DATE_PATTERN = re.compile(r"(\d{4}\.\d{2}\.\d{2})")
NAVER_DAILY_CLOSE_PATTERN = re.compile(
    r'<span class="tah p11">([0-9,]+)</span>',
    re.IGNORECASE,
)
LOGGER = logging.getLogger(__name__)
GCS_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
GCS_OBJECT_API_TEMPLATE = "https://storage.googleapis.com/storage/v1/b/{bucket}/o/{object_name}"
GCS_UPLOAD_API_TEMPLATE = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"


class InvestmentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class InvestmentValidationResult:
    valid: bool
    ticker: str
    security_name: str
    market: str | None
    asset_type: str | None
    message: str


class InvestmentGcsTransactionStore:
    def __init__(self, *, bucket: str, prefix: str) -> None:
        self.bucket = bucket.strip()
        self.prefix = prefix.strip().strip("/") or "investment_status"
        self._access_token = ""
        self._access_token_expires_at = 0.0

    def list_transactions(self, *, user_key: str, account_type: str) -> list[dict[str, Any]]:
        payload, _generation = self._load_payload(
            user_key=user_key,
            account_type=account_type,
        )
        return self._sort_transactions(payload.get("transactions") or [])

    def create_transaction(
        self,
        *,
        user_id: int,
        user_key: str,
        account_type: str,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: float,
        unit_price: float,
        fee: float,
    ) -> dict[str, Any]:
        for _attempt in range(3):
            payload, generation = self._load_payload(
                user_key=user_key,
                account_type=account_type,
            )
            transactions = list(payload.get("transactions") or [])
            now = self._now_iso()
            transaction = {
                "id": self._next_id(transactions),
                "user_id": user_id,
                "account_type": account_type,
                "trade_date": trade_date,
                "ticker": ticker.strip(),
                "security_name": security_name.strip(),
                "side": side,
                "quantity": float(quantity),
                "unit_price": float(unit_price),
                "fee": float(fee),
                "created_at": now,
                "updated_at": now,
            }
            transactions.append(transaction)
            payload = {
                "schema_version": 1,
                "user_key_hash": self._user_key_hash(user_key),
                "account_type": account_type,
                "transactions": self._sort_transactions(transactions),
                "updated_at": now,
            }
            try:
                self._save_payload(
                    user_key=user_key,
                    account_type=account_type,
                    payload=payload,
                    generation=generation,
                )
            except HTTPError as exc:
                if exc.code == 412:
                    continue
                raise
            return transaction
        raise InvestmentValidationError(
            "거래 저장 중 충돌이 발생했습니다. 잠시 후 다시 시도해 주세요."
        )

    def update_transaction(
        self,
        *,
        user_id: int,
        user_key: str,
        account_type: str,
        transaction_id: int,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: float,
        unit_price: float,
        fee: float,
    ) -> dict[str, Any]:
        for _attempt in range(3):
            payload, generation = self._load_payload(
                user_key=user_key,
                account_type=account_type,
            )
            transactions = list(payload.get("transactions") or [])
            now = self._now_iso()
            updated = False
            for index, row in enumerate(transactions):
                if int(row.get("id") or 0) != int(transaction_id):
                    continue
                transactions[index] = {
                    **dict(row),
                    "user_id": user_id,
                    "account_type": account_type,
                    "trade_date": trade_date,
                    "ticker": ticker.strip(),
                    "security_name": security_name.strip(),
                    "side": side,
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "fee": float(fee),
                    "updated_at": now,
                }
                updated = True
                break
            if not updated:
                raise InvestmentValidationError("수정할 거래내역을 찾지 못했습니다.")
            payload = {
                "schema_version": 1,
                "user_key_hash": self._user_key_hash(user_key),
                "account_type": account_type,
                "transactions": self._sort_transactions(transactions),
                "updated_at": now,
            }
            try:
                self._save_payload(
                    user_key=user_key,
                    account_type=account_type,
                    payload=payload,
                    generation=generation,
                )
            except HTTPError as exc:
                if exc.code == 412:
                    continue
                raise
            return dict(transactions[index])
        raise InvestmentValidationError(
            "거래 수정 중 충돌이 발생했습니다. 잠시 후 다시 시도해 주세요."
        )

    def _load_payload(
        self,
        *,
        user_key: str,
        account_type: str,
    ) -> tuple[dict[str, Any], str]:
        object_name = self._object_name(user_key=user_key, account_type=account_type)
        encoded_name = quote(object_name, safe="")
        metadata_url = GCS_OBJECT_API_TEMPLATE.format(
            bucket=quote(self.bucket, safe=""),
            object_name=encoded_name,
        )
        try:
            metadata = self._request_json(metadata_url)
        except HTTPError as exc:
            if exc.code != 404:
                raise
            return self._empty_payload(user_key=user_key, account_type=account_type), "0"
        generation = str(metadata.get("generation") or "0")
        media_url = metadata_url + "?alt=media"
        try:
            payload = self._request_json(media_url)
        except HTTPError as exc:
            if exc.code != 404:
                raise
            return self._empty_payload(user_key=user_key, account_type=account_type), "0"
        if not isinstance(payload, dict):
            return self._empty_payload(user_key=user_key, account_type=account_type), generation
        return payload, generation

    def _save_payload(
        self,
        *,
        user_key: str,
        account_type: str,
        payload: dict[str, Any],
        generation: str,
    ) -> None:
        object_name = self._object_name(user_key=user_key, account_type=account_type)
        query = urlencode(
            {
                "uploadType": "media",
                "name": object_name,
                "ifGenerationMatch": generation or "0",
            }
        )
        url = GCS_UPLOAD_API_TEMPLATE.format(bucket=quote(self.bucket, safe="")) + f"?{query}"
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        with urlopen(request, timeout=10):
            return

    def _request_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self._get_access_token()}"},
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token
        request = Request(GCS_METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._access_token = str(payload["access_token"])
        self._access_token_expires_at = now + float(payload.get("expires_in") or 300)
        return self._access_token

    def _object_name(self, *, user_key: str, account_type: str) -> str:
        return f"{self.prefix}/users/{self._user_key_hash(user_key)}/{account_type}.json"

    def _empty_payload(self, *, user_key: str, account_type: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "user_key_hash": self._user_key_hash(user_key),
            "account_type": account_type,
            "transactions": [],
        }

    def _user_key_hash(self, user_key: str) -> str:
        normalized = str(user_key or "").strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _next_id(self, transactions: list[dict[str, Any]]) -> int:
        ids = [int(row.get("id") or 0) for row in transactions]
        return max(ids, default=0) + 1

    def _sort_transactions(self, transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [dict(row) for row in transactions],
            key=lambda row: (str(row.get("trade_date") or ""), int(row.get("id") or 0)),
            reverse=True,
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InvestmentStatusService:
    def __init__(self, settings: Settings, access_store: AccessStore) -> None:
        self.settings = settings
        self.access_store = access_store
        self.price_db_path = settings.investment_price_db_path
        self._fallback_security_names = self._load_fallback_security_names()
        self._gcs_transaction_store: InvestmentGcsTransactionStore | None = None
        if settings.investment_storage_source == "gcs" and settings.investment_gcs_bucket:
            self._gcs_transaction_store = InvestmentGcsTransactionStore(
                bucket=settings.investment_gcs_bucket,
                prefix=settings.investment_gcs_prefix,
            )

    def list_dashboard(
        self,
        *,
        user_id: int,
        account_type: str,
        user_key: str = "",
    ) -> dict[str, Any]:
        normalized_account_type = self._normalize_account_type(account_type)
        transactions = self._list_transactions(
            user_id=user_id,
            user_key=user_key,
            account_type=normalized_account_type,
        )
        latest_prices = self._load_latest_prices([row["ticker"] for row in transactions])
        holdings = self._build_holdings(transactions, latest_prices)
        totals = {
            "invested_amount": round(
                sum(float(row["invested_amount"] or 0) for row in holdings),
                2,
            ),
            "market_value": round(
                sum(float(row["market_value"] or 0) for row in holdings),
                2,
            ),
        }
        totals["profit_amount"] = round(totals["market_value"] - totals["invested_amount"], 2)
        invested_amount = float(totals["invested_amount"] or 0)
        totals["profit_rate"] = (
            round(totals["profit_amount"] / invested_amount, 6) if invested_amount > 0 else 0.0
        )
        totals["profit_tone"] = self._profit_tone(totals["profit_amount"])
        return {
            "account_type": normalized_account_type,
            "account_label": INVESTMENT_ACCOUNT_LABELS[normalized_account_type],
            "transactions": [self._serialize_transaction(row) for row in transactions],
            "holdings": holdings,
            "totals": self._serialize_totals(totals),
            "price_asof": self._latest_price_date(latest_prices),
            "holding_summary": {
                "lot_count": len(holdings),
                "ticker_count": len({row["ticker"] for row in holdings}),
            },
        }

    def list_performance_history(
        self,
        *,
        user_id: int,
        user_key: str = "",
    ) -> dict[str, Any]:
        transactions_by_account = {
            account_type: self._list_transactions(
                user_id=user_id,
                user_key=user_key,
                account_type=account_type,
            )
            for account_type in INVESTMENT_ACCOUNT_LABELS
        }
        tickers = sorted(
            {
                self._normalize_ticker(str(row.get("ticker") or ""))
                for rows in transactions_by_account.values()
                for row in rows
                if row.get("ticker")
            }
        )
        earliest_trade_date = self._earliest_trade_date(transactions_by_account)
        if earliest_trade_date is None:
            return {
                "has_data": False,
                "start_date": "",
                "end_date": "",
                "accounts": [],
                "chart": {"paths": [], "zero_y": 0, "view_box": "0 0 720 260"},
            }
        price_history = self._load_price_history(tickers)
        latest_prices = self._load_latest_prices(tickers)
        end_date = self._history_end_date(
            transactions_by_account=transactions_by_account,
            price_history=price_history,
            start_date=earliest_trade_date,
        )
        price_history = self._ensure_remote_price_history(
            tickers=tickers,
            price_history=price_history,
            start_date=earliest_trade_date,
            end_date=end_date,
        )
        accounts = []
        all_profit_values: list[float] = [0.0]
        for account_type, transactions in transactions_by_account.items():
            account_start_date = self._earliest_trade_date({account_type: transactions})
            if account_start_date is None:
                accounts.append(
                    {
                        "account_type": account_type,
                        "account_label": INVESTMENT_ACCOUNT_LABELS[account_type],
                        "start_date": "",
                        "end_date": "",
                        "points": [],
                        "latest": {},
                        "profit_tone": "flat",
                        "chart": {
                            "paths": [],
                            "x_ticks": [],
                            "amount_ticks": [],
                            "rate_ticks": [],
                            "zero_y": 0,
                            "view_box": "0 0 820 320",
                        },
                    }
                )
                continue
            dates = self._date_range(account_start_date, end_date)
            points = []
            for current_date in dates:
                day_transactions = [
                    row
                    for row in transactions
                    if str(row.get("trade_date") or "") <= current_date.isoformat()
                ]
                day_prices = self._prices_for_date(
                    tickers=tickers,
                    price_history=price_history,
                    latest_prices=latest_prices,
                    current_date=current_date,
                )
                holdings, realized_profit = self._build_holdings_with_realized(
                    day_transactions,
                    day_prices,
                )
                invested_amount = round(
                    sum(float(row["invested_amount"] or 0) for row in holdings),
                    2,
                )
                market_value = round(
                    sum(float(row["market_value"] or 0) for row in holdings),
                    2,
                )
                profit_amount = round(market_value - invested_amount, 2)
                profit_rate = (
                    round(profit_amount / invested_amount, 6) if invested_amount > 0 else 0.0
                )
                all_profit_values.append(profit_amount)
                all_profit_values.append(realized_profit)
                points.append(
                    {
                        "date": current_date.isoformat(),
                        "invested_amount": invested_amount,
                        "market_value": market_value,
                        "profit_amount": profit_amount,
                        "profit_amount_display": self._format_signed_amount(profit_amount),
                        "profit_rate": profit_rate,
                        "profit_rate_display": self._format_signed_percent(profit_rate),
                        "realized_profit": realized_profit,
                        "realized_profit_display": self._format_signed_amount(realized_profit),
                        "profit_tone": self._profit_tone(profit_amount),
                        "realized_tone": self._profit_tone(realized_profit),
                    }
                )
            latest_point = points[-1] if points else {}
            account_profit_values = [float(point.get("profit_amount") or 0) for point in points] + [
                float(point.get("realized_profit") or 0) for point in points
            ]
            account_chart = self._build_history_chart(
                [
                    {
                        "account_type": account_type,
                        "account_label": INVESTMENT_ACCOUNT_LABELS[account_type],
                        "points": points,
                    }
                ],
                min([0.0, *account_profit_values]),
                max([0.0, *account_profit_values]),
            )
            accounts.append(
                {
                    "account_type": account_type,
                    "account_label": INVESTMENT_ACCOUNT_LABELS[account_type],
                    "start_date": account_start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "points": points,
                    "latest": latest_point,
                    "profit_tone": latest_point.get("profit_tone", "flat"),
                    "chart": account_chart,
                }
            )
        chart = self._build_history_chart(accounts, min(all_profit_values), max(all_profit_values))
        return {
            "has_data": True,
            "start_date": earliest_trade_date.isoformat(),
            "end_date": end_date.isoformat(),
            "accounts": accounts,
            "chart": chart,
        }

    def validate_security(self, *, ticker: str, security_name: str) -> InvestmentValidationResult:
        normalized_ticker = self._normalize_ticker(ticker)
        normalized_name = str(security_name or "").strip()
        if not normalized_ticker:
            return InvestmentValidationResult(
                valid=False,
                ticker="",
                security_name=normalized_name,
                market=None,
                asset_type=None,
                message="종목코드를 입력해 주세요.",
            )
        if not normalized_name:
            return InvestmentValidationResult(
                valid=False,
                ticker=normalized_ticker,
                security_name="",
                market=None,
                asset_type=None,
                message="종목명을 입력해 주세요.",
            )
        row = self._lookup_instrument(normalized_ticker)
        if row is None:
            fallback_name = self._fallback_security_names.get(normalized_ticker)
            if fallback_name:
                if fallback_name != normalized_name:
                    return InvestmentValidationResult(
                        valid=False,
                        ticker=normalized_ticker,
                        security_name=normalized_name,
                        market=None,
                        asset_type=None,
                        message="종목코드와 종목명이 일치하지 않습니다.",
                    )
                return InvestmentValidationResult(
                    valid=True,
                    ticker=normalized_ticker,
                    security_name=fallback_name,
                    market=None,
                    asset_type=None,
                    message="확인됨",
                )
            remote_instrument = self._lookup_remote_instrument(normalized_ticker)
            if remote_instrument:
                canonical_name = str(remote_instrument.get("security_name") or "").strip()
                if canonical_name and canonical_name != normalized_name:
                    return InvestmentValidationResult(
                        valid=False,
                        ticker=normalized_ticker,
                        security_name=normalized_name,
                        market=str(remote_instrument.get("market") or "").strip() or None,
                        asset_type=None,
                        message="종목코드와 종목명이 일치하지 않습니다.",
                    )
                if canonical_name:
                    return InvestmentValidationResult(
                        valid=True,
                        ticker=normalized_ticker,
                        security_name=canonical_name,
                        market=str(remote_instrument.get("market") or "").strip() or None,
                        asset_type=None,
                        message="확인됨",
                    )
            return InvestmentValidationResult(
                valid=False,
                ticker=normalized_ticker,
                security_name=normalized_name,
                market=None,
                asset_type=None,
                message="등록된 종목코드를 찾지 못했습니다.",
            )
        canonical_name = str(row["name"] or "").strip()
        if canonical_name != normalized_name:
            return InvestmentValidationResult(
                valid=False,
                ticker=normalized_ticker,
                security_name=normalized_name,
                market=str(row["market"] or "").strip() or None,
                asset_type=str(row["asset_type"] or "").strip() or None,
                message="종목코드와 종목명이 일치하지 않습니다.",
            )
        return InvestmentValidationResult(
            valid=True,
            ticker=normalized_ticker,
            security_name=canonical_name,
            market=str(row["market"] or "").strip() or None,
            asset_type=str(row["asset_type"] or "").strip() or None,
            message="확인됨",
        )

    def create_transaction(
        self,
        *,
        user_id: int,
        account_type: str,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: str | float | int,
        unit_price: str | float | int,
        fee: str | float | int,
        user_key: str = "",
    ) -> dict[str, Any]:
        normalized_account_type = self._normalize_account_type(account_type)
        normalized_side = self._normalize_side(side)
        quantity_value = self._parse_positive_float(quantity, field_name="수량")
        unit_price_value = self._parse_non_negative_float(unit_price, field_name="단가")
        fee_value = self._parse_non_negative_float(fee, field_name="수수료율")
        try:
            self.access_store._parse_date(str(trade_date).strip())
        except Exception as exc:
            raise InvestmentValidationError("거래일을 YYYY-MM-DD 형식으로 입력해 주세요.") from exc
        validation = self.validate_security(ticker=ticker, security_name=security_name)
        if not validation.valid:
            raise InvestmentValidationError(validation.message)
        transactions = self._list_transactions(
            user_id=user_id,
            user_key=user_key,
            account_type=normalized_account_type,
        )
        current_quantity = self._current_quantity(transactions, validation.ticker)
        if normalized_side == "sell" and quantity_value > current_quantity + 1e-9:
            raise InvestmentValidationError("보유 수량보다 많은 매도는 저장할 수 없습니다.")
        return self._create_transaction(
            user_id=user_id,
            user_key=user_key,
            account_type=normalized_account_type,
            trade_date=str(trade_date).strip(),
            ticker=validation.ticker,
            security_name=validation.security_name,
            side=normalized_side,
            quantity=quantity_value,
            unit_price=unit_price_value,
            fee=fee_value,
        )

    def update_transaction(
        self,
        *,
        user_id: int,
        account_type: str,
        transaction_id: int,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: str | float | int,
        unit_price: str | float | int,
        fee: str | float | int,
        user_key: str = "",
    ) -> dict[str, Any]:
        normalized_account_type = self._normalize_account_type(account_type)
        normalized_side = self._normalize_side(side)
        quantity_value = self._parse_positive_float(quantity, field_name="수량")
        unit_price_value = self._parse_non_negative_float(unit_price, field_name="단가")
        fee_value = self._parse_non_negative_float(fee, field_name="수수료율")
        try:
            self.access_store._parse_date(str(trade_date).strip())
        except Exception as exc:
            raise InvestmentValidationError("거래일을 YYYY-MM-DD 형식으로 입력해 주세요.") from exc
        validation = self.validate_security(ticker=ticker, security_name=security_name)
        if not validation.valid:
            raise InvestmentValidationError(validation.message)
        transactions = self._list_transactions(
            user_id=user_id,
            user_key=user_key,
            account_type=normalized_account_type,
        )
        updated_transactions = []
        found = False
        for row in transactions:
            if int(row.get("id") or 0) == int(transaction_id):
                row = {
                    **dict(row),
                    "trade_date": str(trade_date).strip(),
                    "ticker": validation.ticker,
                    "security_name": validation.security_name,
                    "side": normalized_side,
                    "quantity": quantity_value,
                    "unit_price": unit_price_value,
                    "fee": fee_value,
                }
                found = True
            updated_transactions.append(dict(row))
        if not found:
            raise InvestmentValidationError("수정할 거래내역을 찾지 못했습니다.")
        self._validate_non_negative_positions(updated_transactions)
        return self._update_transaction(
            user_id=user_id,
            user_key=user_key,
            account_type=normalized_account_type,
            transaction_id=transaction_id,
            trade_date=str(trade_date).strip(),
            ticker=validation.ticker,
            security_name=validation.security_name,
            side=normalized_side,
            quantity=quantity_value,
            unit_price=unit_price_value,
            fee=fee_value,
        )

    def _list_transactions(
        self,
        *,
        user_id: int,
        user_key: str,
        account_type: str,
    ) -> list[dict[str, Any]]:
        if self._gcs_transaction_store is not None and user_key:
            return self._gcs_transaction_store.list_transactions(
                user_key=user_key,
                account_type=account_type,
            )
        return self.access_store.list_investment_transactions(
            user_id=user_id,
            account_type=account_type,
        )

    def _create_transaction(
        self,
        *,
        user_id: int,
        user_key: str,
        account_type: str,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: float,
        unit_price: float,
        fee: float,
    ) -> dict[str, Any]:
        if self._gcs_transaction_store is not None and user_key:
            return self._gcs_transaction_store.create_transaction(
                user_id=user_id,
                user_key=user_key,
                account_type=account_type,
                trade_date=trade_date,
                ticker=ticker,
                security_name=security_name,
                side=side,
                quantity=quantity,
                unit_price=unit_price,
                fee=fee,
            )
        return self.access_store.create_investment_transaction(
            user_id=user_id,
            account_type=account_type,
            trade_date=trade_date,
            ticker=ticker,
            security_name=security_name,
            side=side,
            quantity=quantity,
            unit_price=unit_price,
            fee=fee,
        )

    def _update_transaction(
        self,
        *,
        user_id: int,
        user_key: str,
        account_type: str,
        transaction_id: int,
        trade_date: str,
        ticker: str,
        security_name: str,
        side: str,
        quantity: float,
        unit_price: float,
        fee: float,
    ) -> dict[str, Any]:
        if self._gcs_transaction_store is not None and user_key:
            return self._gcs_transaction_store.update_transaction(
                user_id=user_id,
                user_key=user_key,
                account_type=account_type,
                transaction_id=transaction_id,
                trade_date=trade_date,
                ticker=ticker,
                security_name=security_name,
                side=side,
                quantity=quantity,
                unit_price=unit_price,
                fee=fee,
            )
        return self.access_store.update_investment_transaction(
            user_id=user_id,
            account_type=account_type,
            transaction_id=transaction_id,
            trade_date=trade_date,
            ticker=ticker,
            security_name=security_name,
            side=side,
            quantity=quantity,
            unit_price=unit_price,
            fee=fee,
        )

    def _validate_non_negative_positions(self, transactions: list[dict[str, Any]]) -> None:
        quantities: dict[str, float] = {}
        for row in sorted(
            transactions,
            key=lambda item: (str(item.get("trade_date") or ""), int(item.get("id") or 0)),
        ):
            ticker = self._normalize_ticker(str(row.get("ticker") or ""))
            if not ticker:
                continue
            quantity = float(row.get("quantity") or 0)
            side = str(row.get("side") or "").strip().lower()
            delta = quantity if side == "buy" else -quantity
            next_quantity = quantities.get(ticker, 0.0) + delta
            if next_quantity < -1e-9:
                raise InvestmentValidationError("보유 수량보다 많은 매도는 저장할 수 없습니다.")
            quantities[ticker] = max(next_quantity, 0.0)

    def _earliest_trade_date(
        self, transactions_by_account: dict[str, list[dict[str, Any]]]
    ) -> date | None:
        dates = []
        for rows in transactions_by_account.values():
            for row in rows:
                try:
                    dates.append(date.fromisoformat(str(row.get("trade_date") or "")))
                except ValueError:
                    continue
        return min(dates) if dates else None

    def _history_end_date(
        self,
        *,
        transactions_by_account: dict[str, list[dict[str, Any]]],
        price_history: dict[str, list[dict[str, Any]]],
        start_date: date,
    ) -> date:
        candidates = [start_date]
        for rows in transactions_by_account.values():
            for row in rows:
                try:
                    candidates.append(date.fromisoformat(str(row.get("trade_date") or "")))
                except ValueError:
                    continue
        for rows in price_history.values():
            for row in rows:
                try:
                    candidates.append(date.fromisoformat(str(row.get("price_date") or "")))
                except ValueError:
                    continue
        return max(candidates)

    def _date_range(self, start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            return [start_date]
        day_count = (end_date - start_date).days
        return [start_date + timedelta(days=offset) for offset in range(day_count + 1)]

    def _load_price_history(self, tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
        normalized_tickers = [self._normalize_ticker(ticker) for ticker in tickers if ticker]
        normalized_tickers = sorted({ticker for ticker in normalized_tickers if ticker})
        if not normalized_tickers:
            return {}
        placeholders = ",".join("?" for _ in normalized_tickers)
        query = f"""
            SELECT p.ticker, p.close, p.date, im.name, im.market
            FROM prices_daily p
            LEFT JOIN instrument_master im ON im.ticker = p.ticker
            WHERE p.ticker IN ({placeholders})
            ORDER BY p.ticker, p.date
        """
        try:
            with sqlite3.connect(self.price_db_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(query, normalized_tickers).fetchall()
        except sqlite3.Error as exc:
            LOGGER.warning("investment price history unavailable: %s", exc)
            return {}
        history: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in normalized_tickers}
        for row in rows:
            ticker = str(row["ticker"] or "")
            history.setdefault(ticker, []).append(
                {
                    "current_price": float(row["close"] or 0),
                    "price_date": str(row["date"] or ""),
                    "market": str(row["market"] or "").strip(),
                    "security_name": str(row["name"] or "").strip(),
                }
            )
        return history

    def _ensure_remote_price_history(
        self,
        *,
        tickers: list[str],
        price_history: dict[str, list[dict[str, Any]]],
        start_date: date,
        end_date: date,
    ) -> dict[str, list[dict[str, Any]]]:
        normalized_tickers = sorted(
            {self._normalize_ticker(ticker) for ticker in tickers if self._normalize_ticker(ticker)}
        )
        if not normalized_tickers:
            return price_history
        merged = {ticker: list(price_history.get(ticker) or []) for ticker in normalized_tickers}
        for ticker in normalized_tickers:
            local_rows = merged.get(ticker) or []
            has_start_coverage = any(
                str(row.get("price_date") or "") <= start_date.isoformat() for row in local_rows
            )
            if has_start_coverage:
                continue
            remote_rows = self._fetch_naver_daily_prices(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
            )
            if remote_rows:
                merged[ticker] = self._merge_price_rows(local_rows, remote_rows)
        return merged

    def _merge_price_rows(
        self,
        local_rows: list[dict[str, Any]],
        remote_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows_by_date: dict[str, dict[str, Any]] = {}
        for row in remote_rows:
            price_date = str(row.get("price_date") or "")
            if price_date:
                rows_by_date[price_date] = dict(row)
        for row in local_rows:
            price_date = str(row.get("price_date") or "")
            if price_date:
                rows_by_date[price_date] = dict(row)
        return [rows_by_date[key] for key in sorted(rows_by_date)]

    def _fetch_naver_daily_prices(
        self,
        *,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_dates: set[str] = set()
        normalized_ticker = self._normalize_ticker(ticker)
        if not normalized_ticker:
            return rows
        for page in range(1, 16):
            page_rows = self._fetch_naver_daily_price_page(normalized_ticker, page)
            if not page_rows:
                break
            oldest_date: date | None = None
            for row in page_rows:
                price_date_text = str(row.get("price_date") or "")
                try:
                    price_date = date.fromisoformat(price_date_text)
                except ValueError:
                    continue
                oldest_date = min(oldest_date, price_date) if oldest_date else price_date
                if price_date < start_date or price_date > end_date:
                    continue
                if price_date_text in seen_dates:
                    continue
                seen_dates.add(price_date_text)
                rows.append(row)
            if oldest_date is not None and oldest_date < start_date:
                break
        return sorted(rows, key=lambda row: str(row.get("price_date") or ""))

    def _fetch_naver_daily_price_page(self, ticker: str, page: int) -> list[dict[str, Any]]:
        url = NAVER_DAILY_PRICE_URL_TEMPLATE.format(
            ticker=quote(ticker, safe=""),
            page=page,
        )
        request = Request(url, headers=QUOTE_REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=2.5) as response:
                html = response.read().decode("euc-kr", errors="ignore")
        except Exception as exc:
            LOGGER.info("investment daily price remote fetch failed: %s %s", ticker, exc)
            return []
        rows: list[dict[str, Any]] = []
        for match in NAVER_DAILY_ROW_PATTERN.finditer(html):
            row_html = match.group(1)
            date_match = NAVER_DAILY_DATE_PATTERN.search(row_html)
            close_match = NAVER_DAILY_CLOSE_PATTERN.search(row_html)
            if date_match is None or close_match is None:
                continue
            close_value = self._safe_float(close_match.group(1))
            if close_value <= 0:
                continue
            rows.append(
                {
                    "current_price": close_value,
                    "price_date": date_match.group(1).replace(".", "-"),
                    "market": "",
                    "security_name": "",
                }
            )
        return rows

    def _prices_for_date(
        self,
        *,
        tickers: list[str],
        price_history: dict[str, list[dict[str, Any]]],
        latest_prices: dict[str, dict[str, Any]],
        current_date: date,
    ) -> dict[str, dict[str, Any]]:
        prices: dict[str, dict[str, Any]] = {}
        current_date_text = current_date.isoformat()
        for ticker in tickers:
            selected: dict[str, Any] | None = None
            ticker_history = price_history.get(ticker) or []
            for row in ticker_history:
                if str(row.get("price_date") or "") <= current_date_text:
                    selected = row
                else:
                    break
            if selected is None and not ticker_history:
                selected = latest_prices.get(ticker)
            if selected is not None:
                prices[ticker] = dict(selected)
        return prices

    def _build_history_chart(
        self,
        accounts: list[dict[str, Any]],
        min_profit: float,
        max_profit: float,
    ) -> dict[str, Any]:
        width = 640
        height = 170
        padding_left = 58
        padding_right = 58
        padding_top = 24
        padding_bottom = 42
        padding_x = padding_left
        padding_y = padding_top
        chart_right = width - padding_right
        chart_bottom = height - padding_bottom
        chart_width = width - (padding_x * 2)
        chart_width = chart_right - padding_left
        chart_height = chart_bottom - padding_top
        lower = min(min_profit, 0.0)
        upper = max(max_profit, 0.0)
        if abs(upper - lower) < 1e-9:
            padding_value = max(abs(upper), 1000.0)
            lower -= padding_value
            upper += padding_value
        rate_values = [
            float(point.get("profit_rate") or 0)
            for account in accounts
            for point in (account.get("points") or [])
        ]
        rate_lower = min([0.0, *rate_values]) if rate_values else 0.0
        rate_upper = max([0.0, *rate_values]) if rate_values else 0.0
        if abs(rate_upper - rate_lower) < 1e-9:
            padding_rate = max(abs(rate_upper), 0.05)
            rate_lower -= padding_rate
            rate_upper += padding_rate

        def y_for(value: float) -> float:
            return padding_y + ((upper - value) / (upper - lower) * chart_height)

        def rate_y_for(value: float) -> float:
            return padding_y + ((rate_upper - value) / (rate_upper - rate_lower) * chart_height)

        amount_ticks = [
            {
                "value": value,
                "display": self._format_signed_amount(value),
                "y": round(y_for(value), 2),
            }
            for value in self._even_ticks(lower, upper, count=5)
        ]
        rate_ticks = [
            {
                "value": value,
                "display": self._format_signed_percent(value),
                "y": round(rate_y_for(value), 2),
            }
            for value in self._even_ticks(rate_lower, rate_upper, count=5)
        ]
        colors = {"virtual": "#e03131", "live": "#2563eb", "live2": "#16a34a"}
        paths = []
        x_ticks: list[dict[str, Any]] = []
        for account in accounts:
            points = account.get("points") or []
            if not points:
                continue
            max_index = max(len(points) - 1, 1)
            if not x_ticks:
                x_ticks = self._history_x_ticks(
                    points=points,
                    padding_x=padding_x,
                    chart_width=chart_width,
                    label_y=height - 14,
                )
            commands = []
            for index, point in enumerate(points):
                x = padding_x + (index / max_index * chart_width)
                y = y_for(float(point.get("profit_amount") or 0))
                commands.append(f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}")
            rate_commands = []
            for index, point in enumerate(points):
                x = padding_x + (index / max_index * chart_width)
                y = rate_y_for(float(point.get("profit_rate") or 0))
                rate_commands.append(f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}")
            realized_commands = []
            for index, point in enumerate(points):
                x = padding_x + (index / max_index * chart_width)
                y = y_for(float(point.get("realized_profit") or 0))
                realized_commands.append(f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}")
            latest = points[-1]
            account_type = str(account.get("account_type") or "")
            paths.append(
                {
                    "account_type": account_type,
                    "account_label": account.get("account_label") or account_type,
                    "stroke": colors.get(account_type, "#64748b"),
                    "d": " ".join(commands),
                    "rate_d": " ".join(rate_commands),
                    "realized_d": " ".join(realized_commands),
                    "latest_profit_display": latest.get("profit_amount_display", "0"),
                    "latest_rate_display": latest.get("profit_rate_display", "0.00%"),
                    "latest_realized_display": latest.get("realized_profit_display", "0"),
                    "profit_tone": latest.get("profit_tone", "flat"),
                    "realized_tone": latest.get("realized_tone", "flat"),
                }
            )
        return {
            "view_box": f"0 0 {width} {height}",
            "zero_y": round(y_for(0.0), 2),
            "plot": {
                "left": padding_left,
                "right": chart_right,
                "top": padding_top,
                "bottom": chart_bottom,
            },
            "x_ticks": x_ticks,
            "amount_ticks": amount_ticks,
            "rate_ticks": rate_ticks,
            "paths": paths,
            "min_profit_display": self._format_signed_amount(lower),
            "max_profit_display": self._format_signed_amount(upper),
            "min_rate_display": self._format_signed_percent(rate_lower),
            "max_rate_display": self._format_signed_percent(rate_upper),
        }

    def _even_ticks(self, lower: float, upper: float, *, count: int) -> list[float]:
        if count <= 1:
            return [lower]
        step = (upper - lower) / (count - 1)
        return [round(lower + (step * index), 6) for index in range(count)]

    def _history_x_ticks(
        self,
        *,
        points: list[dict[str, Any]],
        padding_x: float,
        chart_width: float,
        label_y: float,
    ) -> list[dict[str, Any]]:
        if not points:
            return []
        tick_days = {5, 10, 15, 20, 25, 30}
        max_index = max(len(points) - 1, 1)
        candidates: list[dict[str, Any]] = []
        seen_dates: set[str] = set()
        for index, point in enumerate(points):
            raw_date = str(point.get("date") or "")
            try:
                point_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if index != 0 and index != len(points) - 1 and point_date.day not in tick_days:
                continue
            if raw_date in seen_dates:
                continue
            seen_dates.add(raw_date)
            x = padding_x + (index / max_index * chart_width)
            label = f"{point_date.month}/{point_date.day}"
            if index == 0 or point_date.day == 5:
                label = f"{str(point_date.year)[2:]}.{point_date.month}/{point_date.day}"
            candidates.append(
                {
                    "date": raw_date,
                    "label": label,
                    "x": round(x, 2),
                    "y": label_y,
                    "is_start": index == 0,
                    "is_end": index == len(points) - 1,
                    "is_endpoint": index in {0, len(points) - 1},
                }
            )
        if len(candidates) <= 2:
            return candidates
        start_x = float(candidates[0]["x"])
        end_x = float(candidates[-1]["x"])
        min_gap = 34.0
        ticks: list[dict[str, Any]] = []
        for candidate in candidates:
            x = float(candidate["x"])
            if candidate["is_endpoint"]:
                ticks.append(candidate)
                continue
            if abs(x - start_x) < min_gap or abs(end_x - x) < min_gap:
                continue
            if ticks and abs(x - float(ticks[-1]["x"])) < min_gap:
                continue
            ticks.append(candidate)
        return ticks

    def _lookup_instrument(self, ticker: str) -> sqlite3.Row | None:
        try:
            with sqlite3.connect(self.price_db_path) as connection:
                connection.row_factory = sqlite3.Row
                return connection.execute(
                    """
                    SELECT ticker, name, market, asset_type, is_active
                    FROM instrument_master
                    WHERE ticker = ? AND is_active = 1
                    LIMIT 1
                    """,
                    (ticker,),
                ).fetchone()
        except sqlite3.Error:
            return None

    def _lookup_remote_instrument(self, ticker: str) -> dict[str, Any] | None:
        quote = self._fetch_naver_quote(ticker)
        if quote and quote.get("security_name"):
            return quote
        return self._fetch_naver_sise_quote(ticker)

    def _load_latest_prices(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        normalized_tickers = [self._normalize_ticker(ticker) for ticker in tickers if ticker]
        normalized_tickers = sorted({ticker for ticker in normalized_tickers if ticker})
        if not normalized_tickers:
            return {}
        placeholders = ",".join("?" for _ in normalized_tickers)
        query = f"""
            SELECT p.ticker, p.close, p.date, im.name, im.market
            FROM prices_daily p
            JOIN (
                SELECT ticker, MAX(date) AS latest_date
                FROM prices_daily
                WHERE ticker IN ({placeholders})
                GROUP BY ticker
            ) latest
              ON latest.ticker = p.ticker
             AND latest.latest_date = p.date
            LEFT JOIN instrument_master im ON im.ticker = p.ticker
            ORDER BY p.ticker
        """
        try:
            with sqlite3.connect(self.price_db_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(query, normalized_tickers).fetchall()
        except sqlite3.Error as exc:
            LOGGER.warning(
                "investment price db unavailable; fallback to remote quotes: %s",
                exc,
            )
            rows = []
        prices = {
            str(row["ticker"]): {
                "current_price": float(row["close"] or 0),
                "price_date": str(row["date"] or ""),
                "market": str(row["market"] or "").strip(),
                "security_name": str(row["name"] or "").strip(),
            }
            for row in rows
        }
        missing_tickers = [ticker for ticker in normalized_tickers if ticker not in prices]
        if missing_tickers:
            prices.update(self._load_remote_latest_prices(missing_tickers))
        return prices

    def _load_remote_latest_prices(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        prices: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            if ticker in prices:
                continue
            price = self._fetch_naver_quote(ticker)
            if price is None:
                price = self._fetch_naver_sise_quote(ticker)
            if price is not None:
                prices[ticker] = price
        return prices

    def _fetch_naver_quote(self, ticker: str) -> dict[str, Any] | None:
        quoted_ticker = quote(ticker, safe="")
        url = NAVER_QUOTE_URL_TEMPLATE.format(ticker=quoted_ticker)
        request = Request(url, headers=QUOTE_REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=2.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        for row in self._iter_naver_quote_rows(payload):
            row_ticker = self._normalize_ticker(str(row.get("cd") or row.get("ticker") or ""))
            if row_ticker != ticker:
                continue
            close_value = self._safe_float(
                row.get("nv")
                or (
                    (row.get("nxtOverMarketPriceInfo") or {}).get("overPrice")
                    if isinstance(row.get("nxtOverMarketPriceInfo"), dict)
                    else None
                )
            )
            if close_value <= 0:
                continue
            return {
                "current_price": close_value,
                "price_date": self._normalize_price_date(row.get("dt") or row.get("tdt")),
                "market": str(row.get("mk") or "").strip(),
                "security_name": str(row.get("nm") or "").strip(),
            }
        return None

    def _fetch_naver_sise_quote(self, ticker: str) -> dict[str, Any] | None:
        url = NAVER_SISE_URL_TEMPLATE.format(ticker=quote(ticker, safe=""))
        request = Request(url, headers=QUOTE_REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=2.5) as response:
                html = response.read().decode("euc-kr", errors="ignore")
        except Exception:
            return None
        match = NAVER_SISE_PRICE_PATTERN.search(html)
        title_match = NAVER_SISE_TITLE_PATTERN.search(html)
        if match is None:
            return None
        close_value = self._safe_float(match.group(1))
        if close_value <= 0:
            return None
        return {
            "current_price": close_value,
            "price_date": date.today().isoformat(),
            "market": "",
            "security_name": title_match.group(1).strip() if title_match else "",
        }

    def _iter_naver_quote_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        result = payload.get("result") if isinstance(payload, dict) else None
        areas = result.get("areas") if isinstance(result, dict) else None
        if not isinstance(areas, list):
            return rows
        for area in areas:
            if not isinstance(area, dict):
                continue
            data_rows = area.get("datas")
            if not isinstance(data_rows, list):
                continue
            for row in data_rows:
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def _normalize_price_date(self, raw_value: Any) -> str:
        text = str(raw_value or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return date.today().isoformat()

    def _safe_float(self, value: Any) -> float:
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    def _build_holdings(
        self,
        transactions: list[dict[str, Any]],
        latest_prices: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        holdings, _realized_profit = self._build_holdings_with_realized(
            transactions,
            latest_prices,
        )
        return holdings

    def _build_holdings_with_realized(
        self,
        transactions: list[dict[str, Any]],
        latest_prices: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], float]:
        lots_by_ticker: dict[str, list[dict[str, Any]]] = {}
        realized_profit = 0.0
        for row in sorted(transactions, key=lambda item: (item["trade_date"], item["id"])):
            ticker = self._normalize_ticker(row["ticker"])
            if not ticker:
                continue
            lots = lots_by_ticker.setdefault(ticker, [])
            quantity = float(row["quantity"] or 0)
            unit_price = float(row["unit_price"] or 0)
            fee_rate = float(row["fee"] or 0)
            fee_amount = self._calculate_fee_amount(quantity, unit_price, fee_rate)
            if row["side"] == "buy":
                lots.append(
                    {
                        "lot_id": int(row["id"]),
                        "trade_date": row["trade_date"],
                        "created_at": row.get("created_at") or "",
                        "updated_at": row.get("updated_at") or "",
                        "ticker": ticker,
                        "security_name": row["security_name"],
                        "market": row.get("market") or "",
                        "quantity": quantity,
                        "cost_basis": (quantity * unit_price) + fee_amount,
                        "unit_price": unit_price,
                        "fee_rate": fee_rate,
                        "fee_amount": fee_amount,
                    }
                )
                continue

            remaining_sell_quantity = quantity
            remaining_sell_fee = fee_amount
            for lot in lots:
                if remaining_sell_quantity <= 1e-9:
                    break
                lot_quantity = float(lot["quantity"] or 0)
                if lot_quantity <= 1e-9:
                    continue
                sell_quantity = min(remaining_sell_quantity, lot_quantity)
                sell_fee_share = (
                    round(fee_amount * (sell_quantity / quantity), 2) if quantity > 0 else 0.0
                )
                if sell_quantity >= remaining_sell_quantity - 1e-9:
                    sell_fee_share = remaining_sell_fee
                average_cost = float(lot["cost_basis"] or 0) / lot_quantity
                cost_basis_sold = average_cost * sell_quantity
                sell_proceeds = (sell_quantity * unit_price) - sell_fee_share
                realized_profit += sell_proceeds - cost_basis_sold
                lot["quantity"] = max(lot_quantity - sell_quantity, 0.0)
                lot["cost_basis"] = max(
                    float(lot["cost_basis"] or 0) - cost_basis_sold,
                    0.0,
                )
                remaining_sell_quantity -= sell_quantity
                remaining_sell_fee = max(remaining_sell_fee - sell_fee_share, 0.0)

        holdings: list[dict[str, Any]] = []
        for ticker, lots in sorted(lots_by_ticker.items()):
            for lot in lots:
                quantity = float(lot["quantity"] or 0)
                if quantity <= 1e-9:
                    continue
                latest = latest_prices.get(ticker) or {}
                current_price = float(latest.get("current_price") or 0)
                average_cost = float(lot["cost_basis"] or 0) / quantity if quantity else 0.0
                if current_price <= 0:
                    current_price = round(average_cost, 2)
                invested_amount = round(average_cost * quantity, 2)
                market_value = round(current_price * quantity, 2)
                profit_amount = round(market_value - invested_amount, 2)
                profit_rate = (
                    round(profit_amount / invested_amount, 6) if invested_amount > 0 else 0.0
                )
                security_name = str(lot["security_name"] or latest.get("security_name") or ticker)
                market = str(latest.get("market") or lot.get("market") or "")
                holdings.append(
                    {
                        "lot_id": lot["lot_id"],
                        "trade_date": lot["trade_date"],
                        "ticker": ticker,
                        "security_name": security_name,
                        "market": market,
                        "quantity": quantity,
                        "quantity_display": self._format_quantity(quantity),
                        "average_buy_price": round(average_cost, 2),
                        "average_buy_price_display": self._format_amount(average_cost),
                        "current_price": current_price,
                        "current_price_display": self._format_amount(current_price),
                        "invested_amount": invested_amount,
                        "invested_amount_display": self._format_amount(invested_amount),
                        "market_value": market_value,
                        "market_value_display": self._format_amount(market_value),
                        "profit_amount": profit_amount,
                        "profit_amount_display": self._format_signed_amount(profit_amount),
                        "profit_rate": profit_rate,
                        "profit_rate_display": self._format_signed_percent(profit_rate),
                        "profit_tone": self._profit_tone(profit_amount),
                        "price_date": latest.get("price_date") or "",
                    }
                )
        return sorted(
            holdings,
            key=lambda row: (row["security_name"], row["trade_date"], row["lot_id"]),
        ), round(realized_profit, 2)

    def _serialize_transaction(self, row: dict[str, Any]) -> dict[str, Any]:
        side = str(row["side"])
        unit_price = float(row["unit_price"] or 0)
        quantity = float(row["quantity"] or 0)
        fee_rate = float(row["fee"] or 0)
        fee_amount = self._calculate_fee_amount(quantity, unit_price, fee_rate)
        invested_amount = (
            (quantity * unit_price) + fee_amount
            if side == "buy"
            else (quantity * unit_price) - fee_amount
        )
        return {
            **row,
            "account_label": INVESTMENT_ACCOUNT_LABELS.get(
                str(row["account_type"]),
                str(row["account_type"]),
            ),
            "side_label": INVESTMENT_SIDE_LABELS.get(side, side),
            "quantity_display": self._format_quantity(quantity),
            "unit_price_display": self._format_amount(unit_price),
            "fee_rate": fee_rate,
            "fee_rate_display": self._format_rate_percent(fee_rate),
            "fee_amount": fee_amount,
            "fee_display": self._format_amount(fee_amount),
            "invested_amount": invested_amount,
            "invested_amount_display": self._format_amount(invested_amount),
        }

    def _serialize_totals(self, totals: dict[str, Any]) -> dict[str, Any]:
        return {
            **totals,
            "invested_amount_display": self._format_amount(float(totals["invested_amount"] or 0)),
            "market_value_display": self._format_amount(float(totals["market_value"] or 0)),
            "profit_amount_display": self._format_signed_amount(
                float(totals["profit_amount"] or 0)
            ),
            "profit_rate_display": self._format_signed_percent(float(totals["profit_rate"] or 0)),
        }

    def _load_fallback_security_names(self) -> dict[str, str]:
        if not FALLBACK_TRADING_SIGN_DETAIL_PATH.exists():
            return {}
        try:
            payload = json.loads(FALLBACK_TRADING_SIGN_DETAIL_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, str] = {}
        for model in payload.get("models") or []:
            for section in model.get("ui_block", {}).get("sections") or []:
                for row in section.get("signals") or []:
                    ticker = self._normalize_ticker(str(row.get("ticker") or ""))
                    name = str(row.get("security_name") or "").strip()
                    if ticker and name and ticker not in out:
                        out[ticker] = name
            for row in model.get("signals") or []:
                ticker = self._normalize_ticker(str(row.get("ticker") or ""))
                name = str(row.get("security_name") or "").strip()
                if ticker and name and ticker not in out:
                    out[ticker] = name
        return out

    def _current_quantity(self, transactions: list[dict[str, Any]], ticker: str) -> float:
        normalized_ticker = self._normalize_ticker(ticker)
        quantity = 0.0
        for row in transactions:
            if self._normalize_ticker(row["ticker"]) != normalized_ticker:
                continue
            side = str(row["side"])
            row_quantity = float(row["quantity"] or 0)
            quantity += row_quantity if side == "buy" else -row_quantity
        return max(quantity, 0.0)

    def _normalize_account_type(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in INVESTMENT_ACCOUNT_LABELS:
            raise InvestmentValidationError("지원하지 않는 계정 유형입니다.")
        return normalized

    def _normalize_side(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in INVESTMENT_SIDE_LABELS:
            raise InvestmentValidationError("매수/매도 구분을 확인해 주세요.")
        return normalized

    def _normalize_ticker(self, value: str) -> str:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits.zfill(6) if digits else ""

    def _parse_positive_float(self, value: str | float | int, *, field_name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise InvestmentValidationError(f"{field_name}을 숫자로 입력해 주세요.") from exc
        if parsed <= 0:
            raise InvestmentValidationError(f"{field_name}은 0보다 커야 합니다.")
        return parsed

    def _parse_non_negative_float(self, value: str | float | int, *, field_name: str) -> float:
        raw = 0 if value in (None, "") else value
        try:
            parsed = float(raw)
        except (TypeError, ValueError) as exc:
            raise InvestmentValidationError(f"{field_name}을 숫자로 입력해 주세요.") from exc
        if parsed < 0:
            raise InvestmentValidationError(f"{field_name}은 0 이상이어야 합니다.")
        return parsed

    def _format_quantity(self, value: float) -> str:
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value)):,}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")

    def _format_amount(self, value: float) -> str:
        return f"{value:,.0f}"

    def _calculate_fee_amount(self, quantity: float, unit_price: float, fee_rate: float) -> float:
        return round(quantity * unit_price * (fee_rate / 100), 2)

    def _format_rate_percent(self, value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".") + "%"

    def _format_signed_amount(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.0f}"

    def _format_signed_percent(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value * 100:.2f}%"

    def _profit_tone(self, value: float) -> str:
        if value > 0:
            return "up"
        if value < 0:
            return "down"
        return "flat"

    def _latest_price_date(self, latest_prices: dict[str, dict[str, Any]]) -> str:
        dates = [
            str(row.get("price_date") or "")
            for row in latest_prices.values()
            if row.get("price_date")
        ]
        return max(dates) if dates else ""
