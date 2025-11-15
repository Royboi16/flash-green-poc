# app/storage.py

"""Persistence helpers for trades, orders, limits and reconciliation state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, NamedTuple, Optional

from app.config import settings

# ─── Database setup ──────────────────────────────────────────────────────────

_DB_PATH = Path("data") / "flash_green.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _column_exists(table: str, column: str) -> bool:
    cur = _conn.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cur.fetchall())


def _create_tables() -> None:
    with _conn:
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qty_mwh    REAL NOT NULL,
                spot_price REAL NOT NULL,
                fut_price  REAL NOT NULL,
                profit     REAL NOT NULL,
                fx_currency TEXT NOT NULL DEFAULT 'GBP',
                counterparty_id TEXT NOT NULL DEFAULT '',
                timestamp  TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id            TEXT PRIMARY KEY,
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL,
                qty_requested REAL NOT NULL,
                qty_filled    REAL NOT NULL,
                avg_price     REAL NOT NULL,
                status        TEXT NOT NULL,
                timestamp     TEXT NOT NULL,
                fx_currency   TEXT NOT NULL DEFAULT 'GBP',
                counterparty_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                qty_mwh REAL NOT NULL,
                avg_price REAL NOT NULL,
                fx_currency TEXT NOT NULL DEFAULT 'GBP',
                counterparty_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(symbol, counterparty_id)
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_balances (
                account_id TEXT NOT NULL,
                currency   TEXT NOT NULL,
                balance    REAL NOT NULL,
                counterparty_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, currency, counterparty_id)
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity   TEXT NOT NULL,
                description TEXT,
                counterparty_id TEXT NOT NULL DEFAULT '',
                fx_currency TEXT NOT NULL DEFAULT 'GBP',
                exposure REAL,
                created_at TEXT NOT NULL
            )
            """
        )

    # ensure legacy dbs get the new columns
    for table, column, ddl in (
        ("trades", "fx_currency", "TEXT NOT NULL DEFAULT 'GBP'"),
        ("trades", "counterparty_id", "TEXT NOT NULL DEFAULT ''"),
        ("orders", "fx_currency", "TEXT NOT NULL DEFAULT 'GBP'"),
        ("orders", "counterparty_id", "TEXT NOT NULL DEFAULT ''"),
    ):
        if not _column_exists(table, column):
            with _conn:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


_create_tables()


# ─── Models ──────────────────────────────────────────────────────────────────


class Order(NamedTuple):
    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str
    timestamp: datetime
    fx_currency: str = settings.default_fx_currency
    counterparty_id: str = settings.default_counterparty_id


@dataclass
class Position:
    symbol: str
    qty_mwh: float
    avg_price: float
    fx_currency: str = settings.default_fx_currency
    counterparty_id: str = settings.default_counterparty_id
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CashBalance:
    account_id: str
    currency: str
    balance: float
    counterparty_id: str = settings.default_counterparty_id
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskEvent:
    event_type: str
    severity: str
    description: str
    counterparty_id: str = settings.default_counterparty_id
    fx_currency: str = settings.default_fx_currency
    exposure: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: Optional[int] = None


@dataclass
class TradeRecord:
    id: int
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float
    fx_currency: str
    counterparty_id: str
    timestamp: datetime


# ─── Trade persistence ───────────────────────────────────────────────────────

def save_trade(
    qty_mwh: float,
    spot_price: float,
    fut_price: float,
    profit: float,
    fx_currency: Optional[str] = None,
    counterparty_id: Optional[str] = None,
) -> TradeRecord:
    """Persist a completed trade (used by your PoC)."""

    ts = datetime.utcnow().isoformat()
    currency = fx_currency or settings.default_fx_currency
    cpty = counterparty_id or settings.default_counterparty_id
    with _conn:
        cur = _conn.execute(
            """
            INSERT INTO trades (qty_mwh, spot_price, fut_price, profit, fx_currency, counterparty_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (qty_mwh, spot_price, fut_price, profit, currency, cpty, ts),
        )

    return TradeRecord(
        id=int(cur.lastrowid),
        qty_mwh=qty_mwh,
        spot_price=spot_price,
        fut_price=fut_price,
        profit=profit,
        fx_currency=currency,
        counterparty_id=cpty,
        timestamp=datetime.fromisoformat(ts),
    )


def get_trades(limit: int = 100) -> List[TradeRecord]:
    """Fetch recent trades for the PnL API."""

    cur = _conn.execute(
        """
        SELECT id, qty_mwh, spot_price, fut_price, profit, fx_currency, counterparty_id, timestamp
          FROM trades
      ORDER BY id DESC
         LIMIT ?
        """,
        (limit,),
    )
    trades: List[TradeRecord] = []
    for row in cur.fetchall():
        trades.append(
            TradeRecord(
                id=row["id"],
                qty_mwh=row["qty_mwh"],
                spot_price=row["spot_price"],
                fut_price=row["fut_price"],
                profit=row["profit"],
                fx_currency=row["fx_currency"],
                counterparty_id=row["counterparty_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
        )
    return trades


# ─── Order‐tracking / idempotency ────────────────────────────────────────────

def save_order(order: Order) -> None:
    """Insert or replace an in‐flight ICE order."""

    ts = order.timestamp.isoformat()
    with _conn:
        _conn.execute(
            """
            INSERT OR REPLACE INTO orders
              (id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp, fx_currency, counterparty_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.symbol,
                order.side,
                order.qty_requested,
                order.qty_filled,
                order.avg_price,
                order.status,
                ts,
                order.fx_currency,
                order.counterparty_id,
            ),
        )


def get_open_orders() -> List[Order]:
    """Return all orders not yet FILLED/CANCELLED/REJECTED."""

    cur = _conn.execute(
        """
        SELECT id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp, fx_currency, counterparty_id
          FROM orders
         WHERE status NOT IN ('FILLED','CANCELLED','REJECTED')
        """
    )
    orders: List[Order] = []
    for row in cur.fetchall():
        orders.append(
            Order(
                id=row["id"],
                symbol=row["symbol"],
                side=row["side"],
                qty_requested=row["qty_requested"],
                qty_filled=row["qty_filled"],
                avg_price=row["avg_price"],
                status=row["status"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                fx_currency=row["fx_currency"],
                counterparty_id=row["counterparty_id"],
            )
        )
    return orders


def update_order(order_id: str, filled: float, avg_price: float, status: str) -> None:
    """Update status/filled/price for an existing order."""

    with _conn:
        _conn.execute(
            "UPDATE orders SET qty_filled=?, avg_price=?, status=? WHERE id=?",
            (filled, avg_price, status, order_id),
        )


# ─── Positions & cash ────────────────────────────────────────────────────────

def upsert_position(position: Position) -> None:
    """Persist or update the latest position snapshot."""

    with _conn:
        _conn.execute(
            """
            INSERT INTO positions (symbol, qty_mwh, avg_price, fx_currency, counterparty_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, counterparty_id)
            DO UPDATE SET qty_mwh=excluded.qty_mwh,
                          avg_price=excluded.avg_price,
                          fx_currency=excluded.fx_currency,
                          updated_at=excluded.updated_at
            """,
            (
                position.symbol,
                position.qty_mwh,
                position.avg_price,
                position.fx_currency,
                position.counterparty_id,
                position.updated_at.isoformat(),
            ),
        )


def get_positions() -> List[Position]:
    cur = _conn.execute(
        """
        SELECT symbol, qty_mwh, avg_price, fx_currency, counterparty_id, updated_at
          FROM positions
      ORDER BY symbol
        """
    )
    positions: List[Position] = []
    for row in cur.fetchall():
        positions.append(
            Position(
                symbol=row["symbol"],
                qty_mwh=row["qty_mwh"],
                avg_price=row["avg_price"],
                fx_currency=row["fx_currency"],
                counterparty_id=row["counterparty_id"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        )
    return positions


def upsert_cash_balance(balance: CashBalance) -> None:
    with _conn:
        _conn.execute(
            """
            INSERT INTO cash_balances (account_id, currency, balance, counterparty_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id, currency, counterparty_id)
            DO UPDATE SET balance=excluded.balance,
                          updated_at=excluded.updated_at
            """,
            (
                balance.account_id,
                balance.currency,
                balance.balance,
                balance.counterparty_id,
                balance.updated_at.isoformat(),
            ),
        )


def get_cash_balances() -> List[CashBalance]:
    cur = _conn.execute(
        """
        SELECT account_id, currency, balance, counterparty_id, updated_at
          FROM cash_balances
      ORDER BY account_id
        """
    )
    balances: List[CashBalance] = []
    for row in cur.fetchall():
        balances.append(
            CashBalance(
                account_id=row["account_id"],
                currency=row["currency"],
                balance=row["balance"],
                counterparty_id=row["counterparty_id"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        )
    return balances


# ─── Risk events ─────────────────────────────────────────────────────────────

def record_risk_event(event: RiskEvent) -> int:
    """Persist a risk-event for controllers."""

    with _conn:
        cur = _conn.execute(
            """
            INSERT INTO risk_events (event_type, severity, description, counterparty_id, fx_currency, exposure, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_type,
                event.severity,
                event.description,
                event.counterparty_id,
                event.fx_currency,
                event.exposure,
                event.created_at.isoformat(),
            ),
        )
    return int(cur.lastrowid)


def get_risk_events(limit: int = 100) -> List[RiskEvent]:
    cur = _conn.execute(
        """
        SELECT id, event_type, severity, description, counterparty_id, fx_currency, exposure, created_at
          FROM risk_events
      ORDER BY id DESC
         LIMIT ?
        """,
        (limit,),
    )
    events: List[RiskEvent] = []
    for row in cur.fetchall():
        events.append(
            RiskEvent(
                id=row["id"],
                event_type=row["event_type"],
                severity=row["severity"],
                description=row["description"],
                counterparty_id=row["counterparty_id"],
                fx_currency=row["fx_currency"],
                exposure=row["exposure"] or 0.0,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        )
    return events


def init_db() -> None:
    """Expose DB init for legacy tests/tools."""

    _create_tables()
