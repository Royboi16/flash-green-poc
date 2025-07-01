# app/storage.py

import sqlite3
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List

# ──────────────────────────────────────────────────────────────────────────────
# Trade record as a Python dataclass
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    id: int
    timestamp: datetime
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float

# ──────────────────────────────────────────────────────────────────────────────
# DB initialization & helpers
# ──────────────────────────────────────────────────────────────────────────────
_DB_PATH = Path("data/trades.db")

def init_db() -> None:
    """Ensure the trades table exists."""
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            qty_mwh     REAL    NOT NULL,
            spot_price  REAL    NOT NULL,
            fut_price   REAL    NOT NULL,
            profit      REAL    NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────────────────────────────────────
# Persistence functions
# ──────────────────────────────────────────────────────────────────────────────
def save_trade(qty_mwh: float, spot_price: float, fut_price: float, profit: float) -> Trade:
    init_db()
    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO trades (timestamp, qty_mwh, spot_price, fut_price, profit) VALUES (?, ?, ?, ?, ?)",
        (ts, qty_mwh, spot_price, fut_price, profit),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return Trade(
        id=trade_id,
        timestamp=datetime.fromisoformat(ts),
        qty_mwh=qty_mwh,
        spot_price=spot_price,
        fut_price=fut_price,
        profit=profit,
    )

def get_trades(limit: int = 100) -> List[Trade]:
    init_db()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, timestamp, qty_mwh, spot_price, fut_price, profit "
        "FROM trades ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        Trade(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            qty_mwh=row["qty_mwh"],
            spot_price=row["spot_price"],
            fut_price=row["fut_price"],
            profit=row["profit"],
        )
        for row in rows
    ]
