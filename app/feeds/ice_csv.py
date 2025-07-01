import csv, itertools, random
from pathlib import Path
from datetime import datetime
from .base import MarketAdapter

class ICECsvFeed(MarketAdapter):
    def __init__(self, csv_path: str):
        # Load all rows; if empty, fall back to a single zero‐price row
        path = Path(csv_path)
        reader = csv.DictReader(path.open())
        rows = list(reader)
        if rows:
            self._cycle = itertools.cycle(rows)
            self._current = next(self._cycle)
        else:
            # no input data → feed 0 £/MWh forever
            self._cycle = itertools.cycle([{"price_gbp_per_mwh": "0"}])
            self._current = {"price_gbp_per_mwh": "0"}

    def quote(self) -> float:
        base = float(self._current["price_gbp_per_mwh"])
        return round(base + random.gauss(0, 0.8), 2)  # tiny intraday wiggle

    def advance(self, _now: datetime = None) -> None:
        self._current = next(self._cycle)

