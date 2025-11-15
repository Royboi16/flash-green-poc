"""Persistence helpers for trades and ICE orders."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_DB_PATH = Path("data") / "flash_green.db"
_conn: Optional[sqlite3.Connection] = None


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    id: int
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float
    timestamp: str


@dataclass
class Order:
    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float = 0.0
    avg_price: float = 0.0
    status: str = "PENDING"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_status_at: Optional[str] = None
    fill_history: List[Dict[str, Any]] = field(default_factory=list)
    cancel_reason: Optional[str] = None
    last_error: Optional[str] = None

    def ensure_timestamps(self) -> "Order":
        now = datetime.utcnow().isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now
        if self.last_status_at is None:
            self.last_status_at = now
        return self


# ─── Connection helpers ───────────────────────────────────────────────────────

def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialise (or reinitialise) the SQLite database."""
    global _DB_PATH, _conn
    if db_path is not None:
        _DB_PATH = Path(db_path)
    if _conn is not None:
        _conn.close()
        _conn = None

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    _conn = conn
    return conn


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        return init_db(_DB_PATH)
    return _conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qty_mwh    REAL NOT NULL,
            spot_price REAL NOT NULL,
            fut_price  REAL NOT NULL,
            profit     REAL NOT NULL,
            timestamp  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id            TEXT PRIMARY KEY,
            symbol        TEXT NOT NULL,
            side          TEXT NOT NULL,
            qty_requested REAL NOT NULL,
            qty_filled    REAL NOT NULL,
            avg_price     REAL NOT NULL,
            status        TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            last_status_at TEXT NOT NULL,
            fill_history  TEXT NOT NULL,
            cancel_reason TEXT,
            last_error    TEXT
        )
        """
    )
    _ensure_column(conn, "orders", "cancel_reason", "TEXT")
    _ensure_column(conn, "orders", "last_error", "TEXT")
    _ensure_column(conn, "orders", "fill_history", "TEXT", "'[]'")
    _ensure_column(conn, "orders", "created_at", "TEXT", "''")
    _ensure_column(conn, "orders", "updated_at", "TEXT", "''")
    _ensure_column(conn, "orders", "last_status_at", "TEXT", "''")


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    col_type: str,
    default: Optional[str] = None,
) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    if column in {row[1] for row in cur.fetchall()}:
        return
    default_clause = f" DEFAULT {default}" if default is not None else ""
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")


# ─── Trade persistence ────────────────────────────────────────────────────────

def save_trade(
    qty_mwh: float,
    spot_price: float,
    fut_price: float,
    profit: float,
) -> Trade:
    ts = datetime.utcnow().isoformat()
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO trades (qty_mwh, spot_price, fut_price, profit, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (qty_mwh, spot_price, fut_price, profit, ts),
        )
        trade_id = cur.lastrowid
    return Trade(
        id=trade_id,
        qty_mwh=qty_mwh,
        spot_price=spot_price,
        fut_price=fut_price,
        profit=profit,
        timestamp=ts,
    )


def get_trades(limit: Optional[int] = None) -> List[Trade]:
    conn = _get_conn()
    sql = "SELECT id, qty_mwh, spot_price, fut_price, profit, timestamp FROM trades ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params: Iterable[Any] = (limit,)
    else:
        params = ()
    cur = conn.execute(sql, params)
    return [Trade(**dict(row)) for row in cur.fetchall()]


# ─── Order persistence ────────────────────────────────────────────────────────

def save_order(order: Order) -> Order:
    order = order.ensure_timestamps()
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders (
                id, symbol, side, qty_requested, qty_filled, avg_price, status,
                created_at, updated_at, last_status_at, fill_history,
                cancel_reason, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.symbol,
                order.side,
                order.qty_requested,
                order.qty_filled,
                order.avg_price,
                order.status,
                order.created_at,
                order.updated_at,
                order.last_status_at,
                json.dumps(order.fill_history or []),
                order.cancel_reason,
                order.last_error,
            ),
        )
    return order


def get_open_orders() -> List[Order]:
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT id, symbol, side, qty_requested, qty_filled, avg_price, status,
               created_at, updated_at, last_status_at, fill_history,
               cancel_reason, last_error
          FROM orders
         WHERE status NOT IN ('FILLED')
        ORDER BY created_at
        """
    )
    return [_row_to_order(row) for row in cur.fetchall()]


def update_order(
    order_id: str,
    *,
    qty_filled: Optional[float] = None,
    avg_price: Optional[float] = None,
    status: Optional[str] = None,
    fill_history: Optional[List[Dict[str, Any]]] = None,
    cancel_reason: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    fields = ["updated_at = ?"]
    params: List[Any] = [datetime.utcnow().isoformat()]
    if qty_filled is not None:
        fields.append("qty_filled = ?")
        params.append(qty_filled)
    if avg_price is not None:
        fields.append("avg_price = ?")
        params.append(avg_price)
    if status is not None:
        fields.append("status = ?")
        params.append(status)
        fields.append("last_status_at = ?")
        params.append(datetime.utcnow().isoformat())
    if fill_history is not None:
        fields.append("fill_history = ?")
        params.append(json.dumps(fill_history))
    if cancel_reason is not None:
        fields.append("cancel_reason = ?")
        params.append(cancel_reason)
    if last_error is not None:
        fields.append("last_error = ?")
        params.append(last_error)

    if len(fields) == 1:
        return

    params.append(order_id)
    conn = _get_conn()
    with conn:
        conn.execute(
            f"UPDATE orders SET {', '.join(fields)} WHERE id = ?",
            params,
        )


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        qty_requested=row["qty_requested"],
        qty_filled=row["qty_filled"],
        avg_price=row["avg_price"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_status_at=row["last_status_at"],
        fill_history=json.loads(row["fill_history"]) if row["fill_history"] else [],
        cancel_reason=row["cancel_reason"],
        last_error=row["last_error"],
    )


# initialise on import
init_db(_DB_PATH)
