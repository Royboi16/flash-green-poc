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
    test_conn = _temp_conn()
    monkeypatch.setattr(storage, "_conn", test_conn)
    storage.save_trade(
        qty_mwh=1.5,
        spot_price=-5.0,
        fut_price=65.0,
        profit=100.0,
    )
    profits = [row["profit"] for row in test_conn.execute("SELECT profit FROM trades").fetchall()]
    assert profits == [100.0]
    trades = storage.get_trades()
    assert len(trades) == 1
    assert trades[0]["profit"] == 100.0


def test_get_trades_orders_by_recency(monkeypatch):
    conn = _temp_conn()
    monkeypatch.setattr(storage, "_conn", conn)
    with conn:
        conn.executemany(
            """
            INSERT INTO trades (qty_mwh, spot_price, fut_price, profit, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1.0, 10.0, 20.0, 5.0, "2024-01-01T00:00:00"),
                (1.1, 11.0, 21.0, 6.0, "2024-01-02T00:00:00"),
                (1.2, 12.0, 22.0, 7.0, "2024-01-02T00:00:00"),
            ],
        )

    trades = storage.get_trades(limit=2)

    assert [t["id"] for t in trades] == [3, 2]
    assert trades[0]["timestamp"] == "2024-01-02T00:00:00"


def test_orders_use_shared_connection(monkeypatch):
    conn = _temp_conn()
    monkeypatch.setattr(storage, "_conn", conn)
    open_order = storage.Order(
        id="o-1",
        symbol="SYM",
        side="BUY",
        qty_requested=10.0,
        qty_filled=0.0,
        avg_price=0.0,
        status="NEW",
        timestamp="2024-01-01T00:00:00",
    )
    filled_order = storage.Order(
        id="o-2",
        symbol="SYM",
        side="SELL",
        qty_requested=5.0,
        qty_filled=5.0,
        avg_price=25.0,
        status="FILLED",
        timestamp="2024-01-01T01:00:00",
    )

    storage.save_order(open_order)
    storage.save_order(filled_order)

    remaining = storage.get_open_orders()

    assert remaining == [open_order]
    assert [row["status"] for row in conn.execute("SELECT status FROM orders ORDER BY id")] == [
        "NEW",
        "FILLED",
    ]
