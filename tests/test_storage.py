from datetime import datetime

import app.db as db
import app.storage as storage
from sqlalchemy import select


def _setup_db():
    engine = db.override_engine("sqlite:///:memory:")
    storage.Base.metadata.create_all(engine)
    return engine


def test_save_and_load():
    _setup_db()
    with db.SessionLocal() as session:
        storage.save_trade(
            qty_mwh=1.5,
            spot_price=-5.0,
            fut_price=65.0,
            profit=100.0,
            session=session,
        )
        profits = [
            row
            for row in session.execute(select(storage.Trade.profit)).scalars().all()
        ]
        assert profits == [100.0]
        trades = storage.get_trades(session=session)
        assert len(trades) == 1
        assert trades[0]["profit"] == 100.0


def test_get_trades_orders_by_recency():
    _setup_db()
    with db.SessionLocal() as session:
        session.add_all(
            [
                storage.Trade(
                    qty_mwh=1.0,
                    spot_price=10.0,
                    fut_price=20.0,
                    profit=5.0,
                    timestamp=datetime.fromisoformat("2024-01-01T00:00:00"),
                ),
                storage.Trade(
                    qty_mwh=1.1,
                    spot_price=11.0,
                    fut_price=21.0,
                    profit=6.0,
                    timestamp=datetime.fromisoformat("2024-01-02T00:00:00"),
                    repo_tx_hash="tx-2",
                    repo_cash_token="CASH",
                    repo_asset_token="ASSET",
                    repo_timestamp=datetime.fromisoformat("2024-01-02T00:00:01"),
                ),
                storage.Trade(
                    qty_mwh=1.2,
                    spot_price=12.0,
                    fut_price=22.0,
                    profit=7.0,
                    timestamp=datetime.fromisoformat("2024-01-02T00:00:00"),
                    repo_tx_hash="tx-3",
                    repo_cash_token="CASH",
                    repo_asset_token="ASSET",
                    repo_timestamp=datetime.fromisoformat("2024-01-02T00:00:02"),
                ),
            ]
        )
        session.commit()

        trades = storage.get_trades(limit=2, session=session)

    assert [t["id"] for t in trades] == [3, 2]
    assert trades[0]["timestamp"] == "2024-01-02T00:00:00"
    assert trades[0]["repo_tx_hash"] == "tx-3"
    assert trades[0]["repo_cash_token"] == "CASH"
    assert trades[0]["repo_asset_token"] == "ASSET"
    assert trades[0]["repo_timestamp"] == "2024-01-02T00:00:02"


def test_orders_use_shared_connection():
    _setup_db()
    open_order = storage.Order(
        id="o-1",
        symbol="SYM",
        side="BUY",
        qty_requested=10.0,
        qty_filled=0.0,
        avg_price=0.0,
        status="NEW",
        timestamp=datetime.fromisoformat("2024-01-01T00:00:00"),
    )
    filled_order = storage.Order(
        id="o-2",
        symbol="SYM",
        side="SELL",
        qty_requested=5.0,
        qty_filled=5.0,
        avg_price=25.0,
        status="FILLED",
        timestamp=datetime.fromisoformat("2024-01-01T01:00:00"),
    )

    with db.SessionLocal() as session:
        storage.save_order(open_order, session=session)
        storage.save_order(filled_order, session=session)

        remaining = storage.get_open_orders(session=session)

        assert remaining == [open_order]

        statuses = [
            row
            for row in session.execute(
                select(storage.OrderRecord.status).order_by(storage.OrderRecord.id)
            ).scalars()
        ]
        assert list(statuses) == ["NEW", "FILLED"]


def test_transactional_session_commits_and_rolls_back():
    _setup_db()

    try:
        with storage.transactional_session() as session:
            storage.save_order(
                storage.Order(
                    id="o-10",
                    symbol="SYM",
                    side="BUY",
                    qty_requested=1.0,
                    qty_filled=1.0,
                    avg_price=50.0,
                    status="PENDING",
                    timestamp=datetime.utcnow(),
                ),
                session=session,
                commit=False,
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    with db.SessionLocal() as session:
        orders = session.execute(select(storage.OrderRecord)).scalars().all()
        assert not orders

    with storage.transactional_session() as session:
        storage.save_order(
            storage.Order(
                id="o-11",
                symbol="SYM",
                side="BUY",
                qty_requested=2.0,
                qty_filled=2.0,
                avg_price=60.0,
                status="PENDING",
                timestamp=datetime.utcnow(),
            ),
            session=session,
            commit=False,
        )
        storage.save_trade(
            qty_mwh=2.0,
            spot_price=10.0,
            fut_price=20.0,
            profit=5.0,
            session=session,
            commit=False,
        )

    with db.SessionLocal() as session:
        orders = session.execute(select(storage.OrderRecord)).scalars().all()
        trades = session.execute(select(storage.Trade)).scalars().all()
        assert len(orders) == 1
        assert len(trades) == 1
