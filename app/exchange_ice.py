import os
import requests
from typing import Any, Dict
from app.config import settings
from app.exchange import Fill

class ICEPowerExchange:
    """
    Adapter for ICE REST API to fetch quotes and place orders.
    """

    def __init__(self):
        # Required settings
        self.base_url = settings.ice_api_url
        self.api_key = settings.ice_api_key
        self.api_secret = settings.ice_api_secret
        self.symbol = settings.ice_symbol  # e.g. "UK_BASELOAD_Q2_2025"

        if not all([self.base_url, self.api_key, self.api_secret, self.symbol]):
            raise RuntimeError("ICE live trading requires ICE_API_URL, ICE_API_KEY, ICE_API_SECRET, and ICE_SYMBOL")

        # Session with authentication header
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-KEY": self.api_key,
            "X-API-SECRET": self.api_secret,
            "Content-Type": "application/json"
        })
        
    def advance(self) -> None:
        """
        No streaming feed to advance—this is a no-op for REST.
        """
        return None

    def quote(self) -> float:
        """
        Fetch the latest market price for the symbol.
        """
        resp = self.session.get(f"{self.base_url}/marketdata/{self.symbol}/price")
        resp.raise_for_status()
        data = resp.json()
        return float(data["last_price"])

    def buy(self, qty_mwh: float, max_price: float) -> Fill:
        """
        Place a limit buy order for qty_mwh at max_price.
        """
        payload = {
            "symbol": self.symbol,
            "side": "BUY",
            "quantity": qty_mwh,
            "price": max_price,
            "type": "LIMIT"
        }
        resp = self.session.post(f"{self.base_url}/orders", json=payload)
        resp.raise_for_status()
        order = resp.json()
        filled = float(order.get("filled_qty", 0))
        avg_price = float(order.get("avg_price", 0))
        return Fill(qty_mwh=filled, price=avg_price)

    def sell(self, qty_mwh: float) -> Fill:
        """
        Place a market sell order for qty_mwh.
        """
        payload = {
            "symbol": self.symbol,
            "side": "SELL",
            "quantity": qty_mwh,
            "type": "MARKET"
        }
        resp = self.session.post(f"{self.base_url}/orders", json=payload)
        resp.raise_for_status()
        order = resp.json()
        filled = float(order.get("filled_qty", 0))
        avg_price = float(order.get("avg_price", 0))
        return Fill(qty_mwh=filled, price=avg_price)

