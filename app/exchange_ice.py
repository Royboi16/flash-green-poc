import time
import requests

from app.config import settings
from app.exchange import Fill


class ICEPowerExchange:
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
        return None

    def quote(self) -> float:
        resp = self.session.get(
            f"{self.base_url}/marketdata/{self.symbol}/price"
        )
        resp.raise_for_status()
        return float(resp.json()["last_price"])

    def buy(self, qty_mwh: float, max_price: float) -> Fill:
        # 1) place limit buy
        payload = {
            "symbol":   self.symbol,
            "side":     "BUY",
            "quantity": qty_mwh,
            "price":    max_price,
            "type":     "LIMIT",
        }
        resp = self.session.post(f"{self.base_url}/orders", json=payload)
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        # 2) poll until filled or timeout
        deadline = time.time() + settings.order_timeout_secs
        filled: float = 0.0
        avg_price: float = 0.0

        while time.time() < deadline:
            o = self._fetch_order(order_id)
            status = o["status"]
            filled = float(o.get("filled_qty", 0))
            avg_price = float(o.get("avg_price", 0))
            if status == "FILLED":
                break
            elif status in ("CANCELLED", "REJECTED"):
                break
            time.sleep(settings.order_poll_interval)

        else:
            # timed out: cancel
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)

    def sell(self, qty_mwh: float) -> Fill:
        # market‐sell (no price cap)
        payload = {
            "symbol":   self.symbol,
            "side":     "SELL",
            "quantity": qty_mwh,
            "type":     "MARKET",
        }
        resp = self.session.post(f"{self.base_url}/orders", json=payload)
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        # poll same as buy
        deadline = time.time() + settings.order_timeout_secs
        filled = 0.0
        avg_price = 0.0

        while time.time() < deadline:
            o = self._fetch_order(order_id)
            status = o["status"]
            filled = float(o.get("filled_qty", 0))
            avg_price = float(o.get("avg_price", 0))
            if status == "FILLED":
                break
            time.sleep(settings.order_poll_interval)
        else:
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)

    def _fetch_order(self, order_id: str) -> dict:
        resp = self.session.get(f"{self.base_url}/orders/{order_id}")
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> None:
        self.session.delete(f"{self.base_url}/orders/{order_id}")
