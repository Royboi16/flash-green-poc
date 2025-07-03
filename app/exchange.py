# app/exchange.py
import time
from dataclasses import dataclass
from app.feeds.bmrs_csv import BMRSCsvFeed
from app.feeds.ice_csv import ICECsvFeed
import ccxt
from typing import Optional, NamedTuple

# our new book
from app.orderbook import OrderBook, Level

@dataclass
class Fill:
    qty_mwh: float
    price: float
    order_id: Optional[str] = None

_pl_feed = BMRSCsvFeed("data/bmrs_spot_uk_2024.csv")
_ice_feed = ICECsvFeed("data/ice_baseload_q2_2024.csv")

class PowerCsvExchange:
    def quote(self): return _pl_feed.quote()
    def advance(self): _pl_feed.advance()
    def buy(self, mwh, max_price):
        price = self.quote()
        if price > max_price: raise RuntimeError("Slipped above max_price")
        return Fill(mwh, price)

class IceCsvExchange:
    def quote(self): return _ice_feed.quote()
    def advance(self): _ice_feed.advance()
    def sell(self, mwh): return Fill(mwh, self.quote())
    
class DepthAwarePowerExchange:
    """
    Wrap a CSV‐price feed with a toy orderbook simulation.
    """
    def __init__(self,
                 latency_ms: int,
                 slippage_bp: float,
                 levels: int,
                 level_size: float):
        self.feed = BMRSCsvFeed("data/bmrs_spot_uk_2024.csv")
        self.latency_ms = latency_ms
        self.slippage_bp = slippage_bp
        self.levels = levels
        self.level_size = level_size

    def quote(self) -> float:
        return self.feed.quote()

    def advance(self) -> None:
        self.feed.advance()

    def buy(self, mwh: float, max_price: float) -> Fill:
        # simulate latency
        time.sleep(self.latency_ms / 1_000)

        base = self.quote()
        # build a toy ask‐side book around base
        asks = [
            Level(price=base + i * 0.5, size=self.level_size)
            for i in range(self.levels)
        ]
        book = OrderBook(bids=[], asks=asks)

        # apply slippage to max_price
        eff_max = max_price * (1 + self.slippage_bp / 10_000)
        lvl = book.match_buy(mwh, eff_max)
        return Fill(lvl.size, lvl.price)
        
class LivePowerExchange:
    """
    A sync CCXT REST ticker adapter. buy() and sell() are instantaneous
    market‐price simulations against the last trade price.
    """
    def __init__(self,
                 exchange_id: str,
                 symbol:      str,
                 api_key:     str | None = None,
                 api_secret:  str | None = None):
        ex_class = getattr(ccxt, exchange_id)
        self.exchange = ex_class({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        self.symbol = symbol

    def quote(self) -> float:
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker["last"])

    def advance(self) -> None:
        # no-op for REST polling
        pass

    def buy(self, mwh: float, max_price: float) -> Fill:
        price = self.quote()
        if price > max_price:
            raise RuntimeError("Slipped above max_price")
        return Fill(mwh, price)

    def sell(self, mwh: float) -> Fill:
        price = self.quote()
        return Fill(mwh, price)

