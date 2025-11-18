"""Live Powerledger market adapter for spot energy quotes and orders."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Dict

import requests

from app.config import settings
from app.exchange import Fill
from app.logger import logger


DEFAULT_TIMEOUT = 10


class PowerledgerExchange:
    """Thin wrapper around a Powerledger REST trading endpoint.

    The adapter is intentionally narrow: it only supports the calls needed by the
    arbitrage loop (quote, buy, sell, fetch/cancel order). Authentication uses an
    org-scoped bearer token carried in ``X-PL-API-Key``; Powerledger typically
    requires the organisation identifier to be echoed back on write operations.
    """

    def __init__(self) -> None:
        self.base_url = settings.powerledger_api_url
        self.api_token = settings.powerledger_api_token
        self.org = settings.powerledger_org
        self.market = settings.powerledger_market

        required = (self.base_url, self.api_token, self.org, self.market)
        if not all(required):
            raise RuntimeError("Missing Powerledger live-trading config")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-PL-API-Key": self.api_token,
                "X-PL-Org": self.org,
                "Content-Type": "application/json",
            }
        )

    def advance(self) -> None:
        return None

    def quote(self) -> float:
        resp = self.session.get(
            f"{self.base_url}/markets/{self.market}/price", timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        body: Dict[str, float] = resp.json()
        return float(body["price_mwh"])

    def buy(self, qty_mwh: float, max_price: float) -> Fill:
        payload = {
            "market": self.market,
            "side": "BUY",
            "quantity_mwh": qty_mwh,
            "max_price": max_price,
            "org": self.org,
            "ts": datetime.utcnow().isoformat(),
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        return self._await_fill(order_id, "BUY")

    def sell(self, qty_mwh: float) -> Fill:
        payload = {
            "market": self.market,
            "side": "SELL",
            "quantity_mwh": qty_mwh,
            "org": self.org,
            "ts": datetime.utcnow().isoformat(),
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order["id"]

        return self._await_fill(order_id, "SELL")

    def fetch_order(self, order_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/orders/{order_id}", timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> None:
        resp = self.session.delete(
            f"{self.base_url}/orders/{order_id}", timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()

    def _await_fill(self, order_id: str, side: str) -> Fill:
        deadline = time.time() + settings.order_timeout_secs
        filled: float = 0.0
        avg_price: float = 0.0

        while time.time() < deadline:
            order = self.fetch_order(order_id)
            status = order["status"]
            filled = float(order.get("filled_qty", 0))
            avg_price = float(order.get("avg_price", 0))
            if status == "FILLED":
                break
            if status in {"CANCELLED", "REJECTED"}:
                logger.warning("Powerledger %s order %s %s", side, order_id, status)
                break
            time.sleep(settings.order_poll_interval)
        else:
            self.cancel_order(order_id)

        return Fill(qty_mwh=filled, price=avg_price, order_id=order_id)
