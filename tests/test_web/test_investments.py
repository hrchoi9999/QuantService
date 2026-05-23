import sqlite3
from dataclasses import replace
from pathlib import Path

from service_platform.web.app import create_app
from service_platform.web.investment_status_api import InvestmentStatusService
from tests.test_web.test_health import build_settings, get_csrf_token, login_user


class FakeGcsInvestmentTransactionStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], list[dict[str, object]]] = {}

    def list_transactions(self, *, user_key: str, account_type: str):
        return list(self.rows.get((user_key.lower(), account_type), []))

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
    ):
        key = (user_key.lower(), account_type)
        rows = self.rows.setdefault(key, [])
        row = {
            "id": len(rows) + 1,
            "user_id": user_id,
            "account_type": account_type,
            "trade_date": trade_date,
            "ticker": ticker,
            "security_name": security_name,
            "side": side,
            "quantity": quantity,
            "unit_price": unit_price,
            "fee": fee,
            "created_at": "2026-04-10T00:00:00+00:00",
            "updated_at": "2026-04-10T00:00:00+00:00",
        }
        rows.append(row)
        return dict(row)

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
    ):
        key = (user_key.lower(), account_type)
        rows = self.rows.setdefault(key, [])
        for index, row in enumerate(rows):
            if int(row["id"]) != int(transaction_id):
                continue
            rows[index] = {
                **row,
                "user_id": user_id,
                "account_type": account_type,
                "trade_date": trade_date,
                "ticker": ticker,
                "security_name": security_name,
                "side": side,
                "quantity": quantity,
                "unit_price": unit_price,
                "fee": fee,
                "updated_at": "2026-04-11T00:00:00+00:00",
            }
            return dict(rows[index])
        raise ValueError("missing transaction")


def seed_price_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE instrument_master (
                ticker TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                asset_type TEXT,
                market TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT,
                asof TEXT,
                source TEXT
            );
            CREATE TABLE prices_daily (
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                value REAL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO instrument_master(ticker, name, asset_type, market, is_active)
            VALUES ('005930', '삼성전자', 'stock', 'KOSPI', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO prices_daily(date, ticker, open, high, low, close, volume, value)
            VALUES ('2026-04-08', '005930', 12000, 12100, 11900, 12000, 100, 1200000)
            """
        )


def build_app_with_investments(tmp_path: Path):
    settings = build_settings(tmp_path)
    price_db_path = tmp_path / "price.db"
    seed_price_db(price_db_path)
    settings = replace(settings, investment_price_db_path=price_db_path)
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="user@example.com",
        password="pass12345",
        phone_number="01012345678",
    )
    return app


def test_investment_page_redirects_when_not_logged_in(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()

    response = client.get("/me/investments", follow_redirects=False)

    assert response.status_code == 302
    assert "/login?next=/me/investments" in response.headers["Location"]


def test_logged_in_user_can_view_investment_page_and_nav(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()

    response = login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "투자 현황" in body
    assert "가상투자" in body
    assert "실투자" in body
    assert "실투자2" in body
    assert "noindex, nofollow" in body
    assert response.headers["Cache-Control"].startswith("no-store")


def test_investment_transaction_save_and_evaluation_flow(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    validate_response = client.post(
        "/api/v1/me/investments/validate-security",
        json={
            "ticker": "005930",
            "security_name": "삼성전자",
            "csrf_token": csrf_token,
        },
    )
    assert validate_response.status_code == 200
    assert validate_response.get_json()["valid"] is True

    save_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 10,
            "unit_price": 10000,
            "fee": 0.1,
            "csrf_token": csrf_token,
        },
    )
    assert save_response.status_code == 201

    dashboard_response = client.get("/api/v1/me/investments/virtual")
    payload = dashboard_response.get_json()

    assert dashboard_response.status_code == 200
    assert payload["holdings"][0]["ticker"] == "005930"
    assert payload["holdings"][0]["current_price"] == 12000.0
    assert payload["holdings"][0]["invested_amount"] == 100100.0
    assert payload["holdings"][0]["market_value"] == 120000.0
    assert payload["holdings"][0]["profit_amount"] == 19900.0
    assert payload["holdings"][0]["profit_tone"] == "up"
    assert payload["transactions"][0]["fee_amount"] == 100.0
    assert payload["transactions"][0]["fee_display"] == "100"

    page_response = client.get("/me/investments?tab=virtual")
    page_body = page_response.get_data(as_text=True)
    assert "profit-up" in page_body
    assert "19,900" in page_body


def test_investment_transaction_rejects_security_mismatch(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "005930",
            "security_name": "삼성전자우",
            "side": "buy",
            "quantity": 10,
            "unit_price": 10000,
            "fee": 0.1,
            "csrf_token": csrf_token,
        },
    )

    assert response.status_code == 400
    assert "종목코드와 종목명이 일치하지 않습니다." in response.get_json()["message"]


def test_investment_save_works_when_price_db_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    def _mock_remote_instrument(self, ticker):
        if ticker == "000270":
            return {
                "current_price": 100000.0,
                "price_date": "2026-04-10",
                "market": "KOSPI",
                "security_name": "기아",
            }
        return None

    monkeypatch.setattr(
        InvestmentStatusService,
        "_lookup_remote_instrument",
        _mock_remote_instrument,
    )
    settings = build_settings(tmp_path)
    settings = replace(settings, investment_price_db_path=tmp_path / "missing_price.db")
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="user@example.com",
        password="pass12345",
        phone_number="01012345678",
    )

    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    save_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "000270",
            "security_name": "기아",
            "side": "buy",
            "quantity": 2,
            "unit_price": 100000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert save_response.status_code == 201

    dashboard = client.get("/api/v1/me/investments/virtual").get_json()
    assert dashboard["holdings"][0]["ticker"] == "000270"
    assert dashboard["holdings"][0]["current_price"] == 100000.0
    assert dashboard["holdings"][0]["profit_amount"] == 0.0


def test_investment_save_uses_remote_security_lookup_when_price_db_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def _mock_remote_instrument(self, ticker):
        if ticker == "005930":
            return {
                "current_price": 206000.0,
                "price_date": "2026-04-10",
                "market": "KOSPI",
                "security_name": "삼성전자",
            }
        return None

    def _mock_remote_prices(self, tickers):
        return {
            "005930": {
                "current_price": 206000.0,
                "price_date": "2026-04-10",
                "market": "KOSPI",
                "security_name": "삼성전자",
            }
        }

    monkeypatch.setattr(
        InvestmentStatusService,
        "_lookup_remote_instrument",
        _mock_remote_instrument,
    )
    monkeypatch.setattr(
        InvestmentStatusService,
        "_load_remote_latest_prices",
        _mock_remote_prices,
    )
    settings = build_settings(tmp_path)
    settings = replace(settings, investment_price_db_path=tmp_path / "missing_price.db")
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="user@example.com",
        password="pass12345",
        phone_number="01012345678",
    )

    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=live")
    csrf_token = get_csrf_token(client)

    save_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "live",
            "trade_date": "2026-04-10",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 1,
            "unit_price": 200000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert save_response.status_code == 201

    dashboard = client.get("/api/v1/me/investments/live").get_json()
    assert dashboard["holdings"][0]["ticker"] == "005930"
    assert dashboard["holdings"][0]["current_price"] == 206000.0
    assert dashboard["holdings"][0]["profit_amount"] == 6000.0


def test_investment_dashboard_uses_remote_price_fallback_for_valuation(
    tmp_path: Path, monkeypatch
) -> None:
    def _mock_remote_instrument(self, ticker):
        if ticker == "000270":
            return {
                "current_price": 115000.0,
                "price_date": "2026-04-10",
                "market": "KOSPI",
                "security_name": "기아",
            }
        return None

    def _mock_remote_prices(self, tickers):
        out = {}
        if "000270" in tickers:
            out["000270"] = {
                "current_price": 115000.0,
                "price_date": "2026-04-10",
                "market": "KOSPI",
                "security_name": "기아",
            }
        return out

    monkeypatch.setattr(
        InvestmentStatusService,
        "_lookup_remote_instrument",
        _mock_remote_instrument,
    )
    monkeypatch.setattr(
        InvestmentStatusService,
        "_load_remote_latest_prices",
        _mock_remote_prices,
    )
    settings = build_settings(tmp_path)
    settings = replace(settings, investment_price_db_path=tmp_path / "missing_price.db")
    app = create_app(settings)
    access_store = app.config["ACCESS_STORE"]
    access_store.register_local_user(
        email="user@example.com",
        password="pass12345",
        phone_number="01012345678",
    )

    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    save_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "000270",
            "security_name": "기아",
            "side": "buy",
            "quantity": 2,
            "unit_price": 100000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert save_response.status_code == 201

    dashboard = client.get("/api/v1/me/investments/virtual").get_json()
    assert dashboard["holdings"][0]["ticker"] == "000270"
    assert dashboard["holdings"][0]["current_price"] == 115000.0
    assert dashboard["holdings"][0]["market_value"] == 230000.0
    assert dashboard["holdings"][0]["profit_amount"] == 30000.0
    assert dashboard["totals"]["invested_amount"] == 200000.0
    assert dashboard["totals"]["market_value"] == 230000.0
    assert dashboard["totals"]["profit_rate"] == 0.15


def test_investment_dashboard_keeps_duplicate_ticker_buys_as_separate_lots(
    tmp_path: Path,
) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=live")
    csrf_token = get_csrf_token(client)

    for trade_date, quantity, unit_price in (
        ("2026-04-07", 70, 10000),
        ("2026-04-08", 30, 11000),
    ):
        response = client.post(
            "/api/v1/me/investments/transactions",
            json={
                "account_type": "live",
                "trade_date": trade_date,
                "ticker": "005930",
                "security_name": "삼성전자",
                "side": "buy",
                "quantity": quantity,
                "unit_price": unit_price,
                "fee": 0,
                "csrf_token": csrf_token,
            },
        )
        assert response.status_code == 201

    dashboard = client.get("/api/v1/me/investments/live").get_json()
    holdings = dashboard["holdings"]

    assert dashboard["holding_summary"] == {"lot_count": 2, "ticker_count": 1}
    assert [row["trade_date"] for row in holdings] == ["2026-04-07", "2026-04-08"]
    assert [row["quantity"] for row in holdings] == [70.0, 30.0]
    assert [row["invested_amount"] for row in holdings] == [700000.0, 330000.0]
    assert [row["market_value"] for row in holdings] == [840000.0, 360000.0]
    assert dashboard["totals"]["invested_amount"] == 1030000.0
    assert dashboard["totals"]["market_value"] == 1200000.0
    assert dashboard["totals"]["profit_amount"] == 170000.0


def test_investment_persistent_store_applies_to_all_account_types(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    fake_store = FakeGcsInvestmentTransactionStore()
    app.config["INVESTMENT_STATUS_SERVICE"]._gcs_transaction_store = fake_store

    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    for account_type in ("virtual", "live", "live2"):
        response = client.post(
            "/api/v1/me/investments/transactions",
            json={
                "account_type": account_type,
                "trade_date": "2026-04-08",
                "ticker": "005930",
                "security_name": "삼성전자",
                "side": "buy",
                "quantity": 3,
                "unit_price": 10000,
                "fee": 0,
                "csrf_token": csrf_token,
            },
        )
        assert response.status_code == 201

        dashboard = client.get(f"/api/v1/me/investments/{account_type}").get_json()
        assert dashboard["holdings"][0]["ticker"] == "005930"
        assert dashboard["holdings"][0]["current_price"] == 12000.0
        assert dashboard["holdings"][0]["market_value"] == 36000.0
        assert dashboard["holdings"][0]["profit_amount"] == 6000.0
        assert dashboard["totals"]["market_value"] == 36000.0
        assert dashboard["totals"]["profit_rate"] == 0.2


def test_live2_account_isolated_from_live_account(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=live2")
    csrf_token = get_csrf_token(client)

    live_save = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "live",
            "trade_date": "2026-04-08",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 5,
            "unit_price": 10000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert live_save.status_code == 201

    live_dashboard = client.get("/api/v1/me/investments/live").get_json()
    live2_dashboard = client.get("/api/v1/me/investments/live2").get_json()

    assert live_dashboard["holding_summary"]["lot_count"] == 1
    assert live2_dashboard["holding_summary"]["lot_count"] == 0


def test_investment_transaction_update_recalculates_evaluation(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    save_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-07",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 10,
            "unit_price": 10000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    transaction_id = save_response.get_json()["transaction"]["id"]

    update_response = client.post(
        f"/api/v1/me/investments/transactions/{transaction_id}",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 5,
            "unit_price": 11000,
            "fee": 0.1,
            "csrf_token": csrf_token,
        },
    )
    assert update_response.status_code == 200

    dashboard = client.get("/api/v1/me/investments/virtual").get_json()
    assert dashboard["holdings"][0]["quantity"] == 5.0
    assert dashboard["holdings"][0]["invested_amount"] == 55055.0
    assert dashboard["holdings"][0]["market_value"] == 60000.0
    assert dashboard["holdings"][0]["profit_amount"] == 4945.0
    assert dashboard["totals"]["profit_rate"] == 0.089819


def test_investment_history_includes_all_three_accounts(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)

    for account_type, quantity in (("virtual", 1), ("live", 2), ("live2", 3)):
        response = client.post(
            "/api/v1/me/investments/transactions",
            json={
                "account_type": account_type,
                "trade_date": "2026-04-08",
                "ticker": "005930",
                "security_name": "삼성전자",
                "side": "buy",
                "quantity": quantity,
                "unit_price": 10000,
                "fee": 0,
                "csrf_token": csrf_token,
            },
        )
        assert response.status_code == 201

    history = client.get("/api/v1/me/investments/history").get_json()
    assert history["has_data"] is True
    assert history["start_date"] == "2026-04-08"
    assert [row["account_type"] for row in history["accounts"]] == [
        "virtual",
        "live",
        "live2",
    ]
    assert [row["latest"]["profit_amount"] for row in history["accounts"]] == [
        2000.0,
        4000.0,
        6000.0,
    ]
    assert len(history["chart"]["paths"]) == 3


def test_investment_history_uses_daily_price_history_without_flat_today_tail(
    tmp_path: Path,
) -> None:
    app = build_app_with_investments(tmp_path)
    price_db_path = app.config["SETTINGS"].investment_price_db_path
    with sqlite3.connect(price_db_path) as connection:
        connection.executemany(
            """
            INSERT INTO prices_daily(date, ticker, open, high, low, close, volume, value)
            VALUES (?, '005930', ?, ?, ?, ?, 100, 1200000)
            """,
            [
                ("2026-04-09", 13000, 13100, 12900, 13000),
                ("2026-04-10", 11000, 11100, 10900, 11000),
            ],
        )
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)
    response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-07",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 1,
            "unit_price": 10000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert response.status_code == 201

    history = client.get("/api/v1/me/investments/history").get_json()
    virtual_history = next(row for row in history["accounts"] if row["account_type"] == "virtual")

    assert virtual_history["end_date"] == "2026-04-10"
    assert [point["profit_amount"] for point in virtual_history["points"]] == [
        0.0,
        2000.0,
        3000.0,
        1000.0,
    ]


def test_investment_history_matches_current_holding_basis_after_sell(tmp_path: Path) -> None:
    app = build_app_with_investments(tmp_path)
    price_db_path = app.config["SETTINGS"].investment_price_db_path
    with sqlite3.connect(price_db_path) as connection:
        connection.executemany(
            """
            INSERT INTO prices_daily(date, ticker, open, high, low, close, volume, value)
            VALUES (?, '005930', ?, ?, ?, ?, 100, 1200000)
            """,
            [
                ("2026-04-09", 13000, 13100, 12900, 13000),
                ("2026-04-10", 11000, 11100, 10900, 11000),
            ],
        )
    client = app.test_client()
    login_user(
        client,
        email="user@example.com",
        password="pass12345",
        next_url="/me/investments",
        follow_redirects=True,
    )
    client.get("/me/investments?tab=virtual")
    csrf_token = get_csrf_token(client)
    buy_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-08",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 1,
            "unit_price": 10000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert buy_response.status_code == 201
    sell_response = client.post(
        "/api/v1/me/investments/transactions",
        json={
            "account_type": "virtual",
            "trade_date": "2026-04-09",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "sell",
            "quantity": 0.5,
            "unit_price": 13000,
            "fee": 0,
            "csrf_token": csrf_token,
        },
    )
    assert sell_response.status_code == 201

    history = client.get("/api/v1/me/investments/history").get_json()
    virtual_history = next(row for row in history["accounts"] if row["account_type"] == "virtual")

    assert [point["profit_amount"] for point in virtual_history["points"]] == [
        2000.0,
        1500.0,
        500.0,
    ]
    assert [point["realized_profit"] for point in virtual_history["points"]] == [
        0.0,
        1500.0,
        1500.0,
    ]
    assert virtual_history["latest"]["profit_rate_display"] == "+10.00%"
    assert virtual_history["latest"]["realized_profit_display"] == "+1,500"
    assert virtual_history["chart"]["paths"][0]["realized_d"]


def test_investment_history_uses_remote_daily_prices_when_price_db_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = replace(
        build_settings(tmp_path),
        investment_price_db_path=tmp_path / "missing_price.db",
    )
    app = create_app(settings)
    service: InvestmentStatusService = app.config["INVESTMENT_STATUS_SERVICE"]
    fake_store = FakeGcsInvestmentTransactionStore()
    service._gcs_transaction_store = fake_store
    user_key = "hrchoi@koreascf.com"
    fake_store.rows[(user_key, "live")] = [
        {
            "id": 1,
            "user_id": 1,
            "account_type": "live",
            "trade_date": "2026-03-13",
            "ticker": "005930",
            "security_name": "삼성전자",
            "side": "buy",
            "quantity": 70.0,
            "unit_price": 196007.0,
            "fee": 0.03,
        },
        {
            "id": 2,
            "user_id": 1,
            "account_type": "live",
            "trade_date": "2026-03-13",
            "ticker": "108490",
            "security_name": "로보티즈",
            "side": "buy",
            "quantity": 60.0,
            "unit_price": 256833.0,
            "fee": 0.03,
        },
        {
            "id": 3,
            "user_id": 1,
            "account_type": "live",
            "trade_date": "2026-03-13",
            "ticker": "494310",
            "security_name": "KODEX 반도체레버리지",
            "side": "buy",
            "quantity": 150.0,
            "unit_price": 70602.0,
            "fee": 0.03,
        },
    ]
    remote_prices = {
        "005930": 183500.0,
        "108490": 258500.0,
        "494310": 65000.0,
    }

    def fake_daily_prices(self, *, ticker, start_date, end_date):
        return [
            {
                "current_price": remote_prices[ticker],
                "price_date": "2026-03-13",
                "market": "",
                "security_name": "",
            }
        ]

    monkeypatch.setattr(InvestmentStatusService, "_fetch_naver_daily_prices", fake_daily_prices)
    monkeypatch.setattr(InvestmentStatusService, "_load_latest_prices", lambda self, tickers: {})

    history = service.list_performance_history(user_id=1, user_key=user_key)
    live_history = next(row for row in history["accounts"] if row["account_type"] == "live")
    first_point = live_history["points"][0]

    assert first_point["date"] == "2026-03-13"
    assert first_point["profit_amount"] == -1627686.23
    assert first_point["profit_rate_display"] == "-4.10%"
