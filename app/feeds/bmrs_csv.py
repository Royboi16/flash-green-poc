import csv
import itertools
from datetime import datetime
from pathlib import Path

from .base import MarketAdapter


class BMRSCsvFeed(MarketAdapter):
    def __init__(self, csv_path: str):
        # Load all rows; if empty, fall back to a single zero‐price row
        path = Path(csv_path)
        reader = csv.DictReader(path.open())
        rows = list(reader)
        if rows:
            self._stream = iter(rows)
            self._current = next(self._stream)
        else:
            # no input data → feed 0 £/MWh forever
            self._stream = itertools.cycle([{"price_gbp_per_mwh": "0"}])
            self._current = {"price_gbp_per_mwh": "0"}

    def quote(self) -> float:
        return float(self._current["price_gbp_per_mwh"])

    def advance(self, _now: datetime | None = None) -> None:
        try:
            self._current = next(self._stream)
        except StopIteration:
            self._stream = itertools.cycle([self._current])  # hold last
