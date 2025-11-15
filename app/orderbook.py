# app/orderbook.py
from dataclasses import dataclass
from typing import List


@dataclass
class Level:
    price: float
    size: float  # how much volume sits at this price


class OrderBook:
    def __init__(self, bids: List[Level], asks: List[Level]):
        # bids: highest→lowest; asks: lowest→highest
        self.bids = sorted(bids, key=lambda L: -L.price)
        self.asks = sorted(asks, key=lambda L: L.price)

    def match_buy(self, qty: float, max_price: float) -> Level:
        """
        Fill up to qty by walking asks ≤ max_price.
        Returns a Level whose price is the VWAP avg and size is filled qty.
        Raises RuntimeError if nothing fills.
        """
        remaining = qty
        cost = 0.0
        for lvl in list(self.asks):
            if lvl.price > max_price or remaining <= 0:
                break
            use = min(lvl.size, remaining)
            cost += use * lvl.price
            lvl.size -= use
            remaining -= use

        filled = qty - remaining
        if filled <= 0:
            raise RuntimeError(
                f"No liquidity to buy {qty} MWh at ≤£{max_price:.2f}"
            )
        return Level(price=cost / filled, size=filled)

    def match_sell(self, qty: float, min_price: float) -> Level:
        """
        Walk bids ≥ min_price. Requires a full fill (otherwise error).
        """
        remaining = qty
        proceeds = 0.0
        for lvl in list(self.bids):
            if lvl.price < min_price or remaining <= 0:
                break
            use = min(lvl.size, remaining)
            proceeds += use * lvl.price
            lvl.size -= use
            remaining -= use

        filled = qty - remaining
        # require full fill
        if filled < qty:
            raise RuntimeError(
                f"No liquidity to sell {qty} MWh at ≥£{min_price:.2f}"
            )
        return Level(price=proceeds / filled, size=filled)
