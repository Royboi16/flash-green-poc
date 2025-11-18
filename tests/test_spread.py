import pytest

from app.strategy import QuoteSnapshot, select_route


def test_select_route_detects_profitable_cycle():
    quotes = QuoteSnapshot(spot_price=10.0, futures_price=50.0, slippage_bp=0.0)
    plan = select_route(quotes)

    assert plan.execute is True
    assert plan.path[0] == plan.path[-1]
    assert plan.expected_profit > 0


def test_select_route_blocks_unprofitable_cycle():
    quotes = QuoteSnapshot(spot_price=50.0, futures_price=50.0, slippage_bp=0.0, loan_fee_rate=0.2)
    plan = select_route(quotes)

    assert plan.execute is False
    assert plan.expected_profit == 0


def test_select_route_rejects_bad_input():
    quotes = QuoteSnapshot(spot_price=-1.0, futures_price=20.0, slippage_bp=0.0)

    select_route(QuoteSnapshot(spot_price=1.0, futures_price=20.0, slippage_bp=0.0))

    with pytest.raises(ValueError):
        select_route(quotes)
