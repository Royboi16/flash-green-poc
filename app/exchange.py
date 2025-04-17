# app/exchange.py
from dataclasses import dataclass
import random

@dataclass
class Fill:
    qty_mwh: float
    price: float

class MockPowerLedger:
    def quote(self) -> float:
        """Random negative/positive spot price (£/MWh)."""
        base = random.gauss(mu=-20, sigma=25)     # ⇒ neg about 40 % of the time
        return round(base, 2)

    def buy(self, mwh: float, max_price: float) -> Fill:
        price = self.quote()
        if price > max_price:
            raise RuntimeError("Slipped above max_price")
        return Fill(qty_mwh=mwh, price=price)


class MockICE:
    def quote(self) -> float:
        """Futures fair value derived from spot + constant premium."""
        return round(65 + random.gauss(mu=0, sigma=3), 2)  # ≈ £65

    def sell(self, mwh: float) -> Fill:
        return Fill(qty_mwh=mwh, price=self.quote())

