# app/storage.py

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, NamedTuple, Dict, Any

# ─── Database setup ──────────────────────────────────────────────────────────

_DB_PATH = Path("data") / "flash_green.db"
_conn: Optional[sqlite3.Connection] = None


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialise (or reinitialise) the sqlite database."""
    global _DB_PATH, _conn
    if db_path is not None:
        _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _conn is not None:
        _conn.close()
    _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _create_tables()
    return _conn


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        init_db(_DB_PATH)
    assert _conn is not None
    return _conn


def _create_tables() -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
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
        conn.execute(
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loan_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference   TEXT,
                event_type  TEXT,
                asset       TEXT,
                amount      REAL,
                fee_bps     REAL,
                tx_hash     TEXT,
                chain_id    INTEGER,
                metadata    TEXT,
                timestamp   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loan_balances (
                asset       TEXT PRIMARY KEY,
                outstanding REAL NOT NULL DEFAULT 0,
                updated_at  TEXT NOT NULL
            )
            """
        )


# ensure DB initialised on import
init_db()


# ─── Models ──────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    id: int
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float
    timestamp: str


class Order(NamedTuple):
    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str
    timestamp: str


class LoanEvent(NamedTuple):
    id: int
    reference: Optional[str]
    event_type: str
    asset: str
    amount: float
    fee_bps: float
    tx_hash: Optional[str]
    chain_id: Optional[int]
    metadata: Optional[Dict[str, Any]]
    timestamp: str


class LoanBalance(NamedTuple):
    asset: str
    outstanding: float
    updated_at: str


# ─── Trade persistence ───────────────────────────────────────────────────────


def save_trade(qty_mwh: float, spot_price: float, fut_price: float, profit: float) -> Trade:
    """Persist a completed trade (used by your PoC)."""
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


def get_trades(limit: int = 100) -> List[Trade]:
    """Fetch past trades for the public API."""
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT id, qty_mwh, spot_price, fut_price, profit, timestamp
          FROM trades
         ORDER BY id DESC
         LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    return [Trade(**dict(row)) for row in rows]


# ─── Order‐tracking / idempotency ────────────────────────────────────────────


def save_order(order: Order) -> None:
    """Insert or replace an in-flight ICE order."""
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders
              (id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp)
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
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT id, symbol, side, qty_requested, qty_filled, avg_price, status, timestamp
          FROM orders
         WHERE status NOT IN ('FILLED','CANCELLED','REJECTED')
        """
    )
    return [Order(**row) for row in cur.fetchall()]


def update_order(order_id: str, filled: float, avg_price: float, status: str) -> None:
    """Update status/filled/price for an existing order."""
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE orders SET qty_filled=?, avg_price=?, status=? WHERE id=?",
            (filled, avg_price, status, order_id),
        )


# ─── Loan tracking ───────────────────────────────────────────────────────────


def _persist_loan_event(
    *,
    event_type: str,
    asset: str,
    amount: float,
    fee_bps: float,
    reference: Optional[str],
    tx_hash: Optional[str],
    chain_id: Optional[int],
    metadata: Optional[Dict[str, Any]],
    delta_sign: int,
) -> LoanEvent:
    ts = datetime.utcnow().isoformat()
    payload = json.dumps(metadata) if metadata else None
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO loan_events (reference, event_type, asset, amount, fee_bps, tx_hash, chain_id, metadata, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (reference, event_type, asset, amount, fee_bps, tx_hash, chain_id, payload, ts),
        )
        conn.execute(
            """
            INSERT INTO loan_balances (asset, outstanding, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(asset) DO UPDATE SET
                outstanding = loan_balances.outstanding + excluded.outstanding,
                updated_at = excluded.updated_at
            """,
            (asset, delta_sign * amount, ts),
        )
        event_id = cur.lastrowid
    return LoanEvent(
        id=event_id,
        reference=reference,
        event_type=event_type,
        asset=asset,
        amount=amount,
        fee_bps=fee_bps,
        tx_hash=tx_hash,
        chain_id=chain_id,
        metadata=metadata,
        timestamp=ts,
    )


def record_loan_drawdown(
    *,
    asset: str,
    amount: float,
    fee_bps: float = 0.0,
    reference: Optional[str] = None,
    tx_hash: Optional[str] = None,
    chain_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LoanEvent:
    """Record a drawdown event."""
    return _persist_loan_event(
        event_type="DRAW",
        asset=asset,
        amount=amount,
        fee_bps=fee_bps,
        reference=reference,
        tx_hash=tx_hash,
        chain_id=chain_id,
        metadata=metadata,
        delta_sign=+1,
    )


def record_loan_repayment(
    *,
    asset: str,
    amount: float,
    fee_bps: float = 0.0,
    reference: Optional[str] = None,
    tx_hash: Optional[str] = None,
    chain_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LoanEvent:
    """Record a repayment event."""
    return _persist_loan_event(
        event_type="REPAY",
        asset=asset,
        amount=amount,
        fee_bps=fee_bps,
        reference=reference,
        tx_hash=tx_hash,
        chain_id=chain_id,
        metadata=metadata,
        delta_sign=-1,
    )


def get_loan_events(limit: int = 100) -> List[LoanEvent]:
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT id, reference, event_type, asset, amount, fee_bps, tx_hash, chain_id, metadata, timestamp
          FROM loan_events
         ORDER BY id DESC
         LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    events: List[LoanEvent] = []
    for row in rows:
        meta = json.loads(row["metadata"]) if row["metadata"] else None
        payload = dict(row)
        payload["metadata"] = meta
        events.append(LoanEvent(**payload))
    return events


def get_loan_balances() -> List[LoanBalance]:
    conn = _get_conn()
    cur = conn.execute(
        """
        SELECT asset, outstanding, updated_at
          FROM loan_balances
         ORDER BY asset
        """
    )
    return [LoanBalance(**row) for row in cur.fetchall()]

