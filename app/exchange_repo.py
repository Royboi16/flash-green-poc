import requests

from app.config import settings
from app.exchange import Fill

DEFAULT_TIMEOUT = 10


class FnalityRepoExchange:
    """Adapter for Fnality×HQLAˣ intraday repo order books."""

    def __init__(self) -> None:
        self.base_url = settings.fnality_repo_api_url
        self.api_token = settings.fnality_repo_api_token
        self.market = settings.fnality_repo_market

        required = (self.base_url, self.api_token, self.market)
        if not all(required):
            raise RuntimeError("Missing Fnality/HQLAˣ repo config")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        )

    def advance(self) -> None:
        # live order book polled on demand
        return None

    def _best_bid(self) -> float:
        resp = self.session.get(
            f"{self.base_url}/markets/{self.market}/orderbook", timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        body = resp.json()
        bids = body.get("bids") or []
        if not bids:
            raise RuntimeError("Fnality/HQLAˣ orderbook has no bids")
        top = bids[0]
        return float(top["price"])

    def quote(self) -> float:
        return self._best_bid()

    def sell(self, qty_mwh: float) -> Fill:
        price = self._best_bid()
        payload = {
            "market": self.market,
            "side": "SELL",
            "quantity_mwh": qty_mwh,
            "price": price,
        }
        resp = self.session.post(
            f"{self.base_url}/orders", json=payload, timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        body = resp.json()
        return Fill(qty_mwh=qty_mwh, price=price, order_id=body.get("id"))
