# app/storage.py

from contextlib import contextmanager
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Iterator

# ─── Database setup ──────────────────────────────────────────────────────────

_DB_PATH = Path("data") / "flash_green.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")


def _create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, isolation_level=None)
    _configure_connection(conn)
    return conn


_conn: sqlite3.Connection | None = None


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = _create_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _ensure_conn(conn: sqlite3.Connection | None) -> tuple[sqlite3.Connection, bool]:
    if _conn is not None and conn is None:
        return _conn, False
    if conn is not None:
        return conn, False
    return _create_connection(), True


def _close_if_owned(conn: sqlite3.Connection, owns: bool) -> None:
    if owns:
        conn.close()


def _init_schema() -> None:
    with get_connection() as conn:
        with transaction(conn):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    qty_mwh    REAL,
                    spot_price REAL,
                    fut_price  REAL,
                    profit     REAL,
                    timestamp  TEXT,
                    repo_tx_hash TEXT,
                    repo_cash_token TEXT,
                    repo_asset_token TEXT,
                    repo_timestamp TEXT
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

            existing_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(trades)")
            }
            if "repo_tx_hash" not in existing_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN repo_tx_hash TEXT")
            if "repo_cash_token" not in existing_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN repo_cash_token TEXT")
            if "repo_asset_token" not in existing_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN repo_asset_token TEXT")
            if "repo_timestamp" not in existing_cols:
                conn.execute("ALTER TABLE trades ADD COLUMN repo_timestamp TEXT")


_init_schema()


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
    repo_tx_hash: str | None = None,
    repo_cash_token: str | None = None,
    repo_asset_token: str | None = None,
    repo_timestamp: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist a completed trade (used by your PoC)."""
    ts = datetime.utcnow().isoformat()
    connection, owns_conn = _ensure_conn(conn)
    try:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO trades
                    (
                        qty_mwh,
                        spot_price,
                        fut_price,
                        profit,
                        timestamp,
                        repo_tx_hash,
                        repo_cash_token,
                        repo_asset_token,
                        repo_timestamp
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    qty_mwh,
                    spot_price,
                    fut_price,
                    profit,
                    ts,
                    repo_tx_hash,
                    repo_cash_token,
                    repo_asset_token,
                    repo_timestamp,
                ),
            )
    finally:
        _close_if_owned(connection, owns_conn)


def get_trades(limit: int | None = None, conn: sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
    """Fetch past trades for your PnL API ordered by recency."""
    sql = """
        SELECT
            id,
            qty_mwh,
            spot_price,
            fut_price,
            profit,
            timestamp,
            repo_tx_hash,
            repo_cash_token,
            repo_asset_token,
            repo_timestamp
          FROM trades
         ORDER BY timestamp DESC, id DESC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)

    connection, owns_conn = _ensure_conn(conn)
    try:
        cur = connection.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        _close_if_owned(connection, owns_conn)


def get_pnl_totals(conn: sqlite3.Connection | None = None) -> Dict[str, float]:
    """Aggregate net, positive, and negative PnL from stored trades."""
    connection, owns_conn = _ensure_conn(conn)
    try:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN profit >= 0 THEN profit ELSE 0 END), 0) AS positive,
                COALESCE(SUM(CASE WHEN profit < 0 THEN -profit ELSE 0 END), 0) AS negative,
                COALESCE(SUM(profit), 0) AS net
            FROM trades
            """
        ).fetchone()
        return {
            "positive": float(row["positive"]),
            "negative": float(row["negative"]),
            "net": float(row["net"]),
        }
    finally:
        _close_if_owned(connection, owns_conn)


# ─── Order‐tracking / idempotency ────────────────────────────────────────────


def save_order(order: Order, conn: sqlite3.Connection | None = None) -> None:
    """Insert or replace an in‐flight ICE order."""
    connection, owns_conn = _ensure_conn(conn)
    try:
        with transaction(connection):
            connection.execute(
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
    finally:
        _close_if_owned(connection, owns_conn)


def get_open_orders(conn: sqlite3.Connection | None = None) -> List[Order]:
    """Return all orders not yet FILLED/CANCELLED/REJECTED."""
    connection, owns_conn = _ensure_conn(conn)
    try:
        cur = connection.execute(
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
    finally:
        _close_if_owned(connection, owns_conn)


def update_order(
    order_id: str,
    filled: float,
    avg_price: float,
    status: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update status/filled/price for an existing order."""
    connection, owns_conn = _ensure_conn(conn)
    try:
        with transaction(connection):
            connection.execute(
                """
                UPDATE orders
                   SET qty_filled=?, avg_price=?, status=?
                 WHERE id=?
                """,
                (filled, avg_price, status, order_id),
            )
    finally:
        _close_if_owned(connection, owns_conn)


# ─── FastAPI dependency helper ───────────────────────────────────────────────


def connection_dependency() -> Iterator[sqlite3.Connection]:
    """Yield a configured connection for FastAPI dependencies."""
    with get_connection() as conn:
        yield conn
