import sqlite3

import app.storage as storage


def _temp_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qty_mwh REAL,
            spot_price REAL,
            fut_price REAL,
            profit REAL,
            timestamp TEXT
        );
        CREATE TABLE orders (
            id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty_requested REAL,
            qty_filled REAL,
            avg_price REAL,
            status TEXT,
            timestamp TEXT
        );
        """
    )
    return conn


def test_save_and_load(monkeypatch):
    monkeypatch.setattr(storage, "_conn", _temp_conn())
    storage.save_trade(
        qty_mwh=1.5,
        spot_price=-5.0,
        fut_price=65.0,
        profit=100.0,
    )
    trades = storage.get_trades()
    assert len(trades) == 1
    assert trades[0]["profit"] == 100.0
