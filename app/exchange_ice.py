import time
from typing import Tuple

import requests

from app.config import settings
from app.exchange import Fill


DEFAULT_TIMEOUT = 10


class _ICERestBase:
    def __init__(self) -> None:
        self.base_url = settings.ice_api_url
        self.api_key = settings.ice_api_key
        self.api_secret = settings.ice_api_secret
        self.symbol = settings.ice_symbol
        required = (
            self.base_url,
            self.api_key,
            self.api_secret,
            self.symbol,
        )
        if not all(required):
            raise RuntimeError("Missing ICE live-trading config")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-KEY": self.api_key,
                "X-API-SECRET": self.api_secret,
                "Content-Type": "application/json",
            }
        )

    def advance(self) -> None:
        # real REST endpoints are polled on each call
        return None

    def _fetch_orderbook(self) -> Tuple[float | None, float | None]:
        resp = self.session.get(
            f"{self.base_url}/marketdata/{self.symbol}/orderbook",
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        bids = body.get("bids") or []
        asks = body.get("asks") or []

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask

    def fetch_order(self, order_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/orders/{order_id}", timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> None:
        self.session.delete(
            f"{self.base_url}/orders/{order_id}", timeout=DEFAULT_TIMEOUT
        )


class ICEPowerExchange(_ICERestBase):
    def quote(self) -> float:
        bid, ask = self._fetch_orderbook()
        if ask is None:
            raise RuntimeError("ICE orderbook has no asks; cannot price BUY leg")
        return ask

    def buy(self, qty_mwh: float, max_price: float) -> Fill:
        bid, ask = self._fetch_orderbook()
        target_price = ask if ask is not None else max_price
        if target_price > max_price:
            raise RuntimeError("ICE ask above max_price")

        payload = {
            "symbol":   self.symbol,
            "side":     "BUY",
            "quantity": qty_mwh,
            "price":    target_price,
            "type":     "LIMIT",
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        deadline = time.time() + settings.order_timeout_secs
        filled: float = 0.0
        avg_price: float = 0.0

        while time.time() < deadline:
            o = self.fetch_order(order_id)
            status = o["status"]
            filled = float(o.get("filled_qty", 0))
            avg_price = float(o.get("avg_price", 0))
            if status == "FILLED":
                break
            if status in ("CANCELLED", "REJECTED"):
                break
            time.sleep(settings.order_poll_interval)
        else:
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)

    def sell(self, qty_mwh: float) -> Fill:
        bid, ask = self._fetch_orderbook()
        target_price = bid if bid is not None else 0.0
        payload = {
            "symbol":   self.symbol,
            "side":     "SELL",
            "quantity": qty_mwh,
            "price":    target_price,
            "type":     "LIMIT",
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        deadline = time.time() + settings.order_timeout_secs
        filled = 0.0
        avg_price = 0.0

        while time.time() < deadline:
            o = self.fetch_order(order_id)
            status = o["status"]
            filled = float(o.get("filled_qty", 0))
            avg_price = float(o.get("avg_price", 0))
            if status == "FILLED":
                break
            time.sleep(settings.order_poll_interval)
        else:
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)


class ICERepoFuturesExchange(_ICERestBase):
    """Futures leg mapped to ICE REST orderbook + order entry."""

    def quote(self) -> float:
        bid, _ = self._fetch_orderbook()
        if bid is None:
            raise RuntimeError("ICE orderbook has no bids; cannot price SELL leg")
        return bid

    def sell(self, qty_mwh: float) -> Fill:
        bid, _ = self._fetch_orderbook()
        if bid is None:
            raise RuntimeError("ICE orderbook has no bids; cannot execute SELL leg")

        payload = {
            "symbol":   self.symbol,
            "side":     "SELL",
            "quantity": qty_mwh,
            "price":    bid,
            "type":     "LIMIT",
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        deadline = time.time() + settings.order_timeout_secs
        filled = 0.0
        avg_price = 0.0

        while time.time() < deadline:
            o = self.fetch_order(order_id)
            status = o["status"]
            filled = float(o.get("filled_qty", 0))
            avg_price = float(o.get("avg_price", 0))
            if status == "FILLED":
                break
            if status in ("CANCELLED", "REJECTED"):
                break
            time.sleep(settings.order_poll_interval)
        else:
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)
