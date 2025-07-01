import os
import sqlite3
from pathlib import Path
from app.storage import init_db, save_trade, get_trades, _DB_PATH

def test_save_and_load(tmp_path, monkeypatch):
    # isolate to a temp DB
    test_db = tmp_path / "test.db"
    monkeypatch.setattr("app.storage._DB_PATH", test_db)

    # start fresh
    if test_db.exists(): test_db.unlink()
    init_db()

    t = save_trade(qty_mwh=1.5, spot_price=-5.0, fut_price=65.0, profit=100.0)
    assert t.id == 1
    recs = get_trades(limit=10)
    assert len(recs) == 1
    assert recs[0].profit == 100.0


