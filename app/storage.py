"""SQLite persistence helpers for trades and orders."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping, Optional, Union


__all__ = [
    "Trade",
    "Order",
    "_DB_PATH",
    "init_db",
    "save_trade",
    "get_trades",
    "save_order",
    "get_open_orders",
    "update_order",
]


_DB_PATH = Path("data") / "flash_green.db"
_connection: sqlite3.Connection | None = None


@dataclass
class Trade:
    """Serialized representation of a completed trade."""

    id: int
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float
    timestamp: datetime


@dataclass
class Order:
    """Basic representation of an ICE order."""

    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str
    timestamp: str


def init_db() -> None:
    """Initialise the SQLite database and ensure required tables exist."""

    global _connection

    if _connection is not None:
        _connection.close()

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _connection = sqlite3.connect(
        str(_DB_PATH),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    _connection.row_factory = sqlite3.Row

    with _connection:
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qty_mwh    REAL,
                spot_price REAL,
                fut_price  REAL,
                profit     REAL,
                timestamp  TEXT
            )
            """
        )
        _connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id            TEXT PRIMARY KEY,
                symbol        TEXT,
                side          TEXT,
                qty_requested REAL,
                qty_filled    REAL,
                avg_price     REAL,
                status        TEXT,
                timestamp     TEXT
            )
            """
        )


def _get_connection() -> sqlite3.Connection:
    if _connection is None:
        init_db()
    assert _connection is not None
    return _connection


def save_trade(qty_mwh: float, spot_price: float, fut_price: float, profit: float) -> Trade:
    """Persist a completed trade and return the stored record."""

    conn = _get_connection()
    ts = datetime.utcnow()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (qty_mwh, spot_price, fut_price, profit, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (qty_mwh, spot_price, fut_price, profit, ts.isoformat()),
        )
    trade_id = int(cursor.lastrowid)
    return Trade(trade_id, qty_mwh, spot_price, fut_price, profit, ts)


def get_trades(limit: Optional[int] = None) -> List[Trade]:
    """Fetch stored trades ordered by insertion."""

    conn = _get_connection()
    query = "SELECT id, qty_mwh, spot_price, fut_price, profit, timestamp FROM trades ORDER BY id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    rows = conn.execute(query, params).fetchall()
    trades: List[Trade] = []
    for row in rows:
        trades.append(
            Trade(
                id=row["id"],
                qty_mwh=row["qty_mwh"],
                spot_price=row["spot_price"],
                fut_price=row["fut_price"],
                profit=row["profit"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
        )
    return trades


def save_order(order: Union[Order, Mapping[str, Any]]) -> None:
    """Insert or replace an order record."""

    conn = _get_connection()
    payload = order.__dict__ if isinstance(order, Order) else dict(order)
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp)
            VALUES (:id, :symbol, :side, :qty_requested, :qty_filled, :avg_price, :status, :timestamp)
            """,
            payload,
        )


def get_open_orders() -> List[Order]:
    """Return all orders that are still active."""

    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp
        FROM orders
        WHERE status NOT IN ('FILLED','CANCELLED','REJECTED')
        ORDER BY timestamp
        """
    ).fetchall()
    return [Order(**dict(row)) for row in rows]


def update_order(order_id: str, filled: float, avg_price: float, status: str) -> None:
    """Update order fill information."""

    conn = _get_connection()
    with conn:
        conn.execute(
            "UPDATE orders SET qty_filled=?, avg_price=?, status=? WHERE id=?",
            (filled, avg_price, status, order_id),
        )


# Prepare the default database on import.
init_db()

