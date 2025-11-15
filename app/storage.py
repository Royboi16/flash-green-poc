# app/storage.py

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

# ─── Database setup ──────────────────────────────────────────────────────────

_DB_PATH = Path("data") / "flash_green.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_conn.row_factory = sqlite3.Row

# Create tables if they don't exist
with _conn:
    _conn.execute(
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
    _conn.execute(
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

# ─── Models ──────────────────────────────────────────────────────────────────


class Order(NamedTuple):
    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str
    timestamp: str

# ─── Trade persistence ───────────────────────────────────────────────────────


def save_trade(
    qty_mwh: float,
    spot_price: float,
    fut_price: float,
    profit: float,
) -> None:
    """Persist a completed trade (used by your PoC)."""
    ts = datetime.utcnow().isoformat()
    with _conn:
        _conn.execute(
            """
            INSERT INTO trades
                (qty_mwh, spot_price, fut_price, profit, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (qty_mwh, spot_price, fut_price, profit, ts),
        )


def get_trades() -> List[Dict[str, Any]]:
    """Fetch all past trades for your PnL API."""
    cur = _conn.execute(
        """
        SELECT qty_mwh, spot_price, fut_price, profit, timestamp
          FROM trades
         ORDER BY id
        """
    )
    return [dict(row) for row in cur.fetchall()]

# ─── Order‐tracking / idempotency ────────────────────────────────────────────


def save_order(order: Order) -> None:
    """Insert or replace an in‐flight ICE order."""
    with _conn:
        _conn.execute(
            """
            INSERT OR REPLACE INTO orders (
                id, symbol, side, qty_requested,
                qty_filled, avg_price, status, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.symbol,
                order.side,
                order.qty_requested,
                order.qty_filled,
                order.avg_price,
                order.status,
                order.timestamp,
            ),
        )


def get_open_orders() -> List[Order]:
    """Return all orders not yet FILLED/CANCELLED/REJECTED."""
    cur = _conn.execute(
        """
        SELECT
            id,
            symbol,
            side,
            qty_requested,
            qty_filled,
            avg_price,
            status,
            timestamp
          FROM orders
         WHERE status NOT IN ('FILLED','CANCELLED','REJECTED')
        """
    )
    return [Order(**row) for row in cur.fetchall()]


def update_order(
    order_id: str,
    filled: float,
    avg_price: float,
    status: str,
) -> None:
    """Update status/filled/price for an existing order."""
    with _conn:
        _conn.execute(
            """
            UPDATE orders
               SET qty_filled=?, avg_price=?, status=?
             WHERE id=?
            """,
            (filled, avg_price, status, order_id),
        )
