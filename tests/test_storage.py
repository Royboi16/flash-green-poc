import pytest

from app.storage import (
    Order,
    get_open_orders,
    get_trades,
    init_db,
    save_order,
    save_trade,
    update_order,
)


def test_trade_and_order_metadata(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)

    trade = save_trade(qty_mwh=1.5, spot_price=-5.0, fut_price=65.0, profit=100.0)
    trades = get_trades()
    assert len(trades) == 1
    assert trades[0].id == trade.id
    assert trades[0].profit == pytest.approx(100.0)

    order = save_order(
        Order(
            id="order-1",
            symbol="UK_BASE",
            side="BUY",
            qty_requested=10.0,
            status="PENDING",
        )
    )
    open_orders = get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].fill_history == []

    fills = [{"qty": 4.0, "price": 45.0, "timestamp": "2024-01-01T00:00:00Z"}]
    update_order(
        order.id,
        qty_filled=4.0,
        avg_price=45.0,
        status="PARTIALLY_FILLED",
        fill_history=fills,
        cancel_reason="timeout",
    )
    refreshed = get_open_orders()[0]
    assert refreshed.qty_filled == pytest.approx(4.0)
    assert refreshed.cancel_reason == "timeout"
    assert refreshed.fill_history == fills

    update_order(order.id, status="FILLED")
    assert get_open_orders() == []
