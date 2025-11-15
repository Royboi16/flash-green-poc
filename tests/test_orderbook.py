import pytest

from app.orderbook import Level, OrderBook


def test_match_buy_full():
    book = OrderBook(
        bids=[],
        asks=[Level(price=10, size=5), Level(price=12, size=5)],
    )
    lvl = book.match_buy(qty=7, max_price=12)
    assert pytest.approx(lvl.price, rel=1e-6) == 74 / 7
    assert lvl.size == 7


def test_match_buy_partial():
    book = OrderBook(bids=[], asks=[Level(price=20, size=3)])
    lvl = book.match_buy(qty=5, max_price=20)
    assert lvl.size == 3
    assert lvl.price == 20


def test_match_sell_no_liquidity():
    book = OrderBook(bids=[Level(price=15, size=2)], asks=[])
    with pytest.raises(RuntimeError):
        book.match_sell(qty=5, min_price=15)
