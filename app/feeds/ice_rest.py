"""Broker/ICE REST futures market data adapter."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional

import requests

from .base import MarketAdapter


class _RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self.max_calls = max_calls
        self.period = period_seconds
        self._window: Deque[float] = deque()

    def wait(self) -> None:
        if self.max_calls <= 0:
            return
        now = time.monotonic()
        while self._window and now - self._window[0] >= self.period:
            self._window.popleft()
        if len(self._window) >= self.max_calls:
            sleep_for = self.period - (now - self._window[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            while self._window and now - self._window[0] >= self.period:
                self._window.popleft()
        self._window.append(time.monotonic())


class BrokerFuturesLiveFeed(MarketAdapter):
    """Simple authenticated adapter for ICE/OTC broker quote endpoints."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        symbol: str,
        session: Optional[requests.Session] = None,
        page_size: int = 24,
        max_retries: int = 3,
        rate_limit_per_minute: int = 20,
        timeout: float = 10.0,
    ) -> None:
        if not all([base_url, username, password, symbol]):
            raise ValueError("ICE live feed requires base_url, credentials and symbol")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.symbol = symbol
        self.session = session or requests.Session()
        self.session.auth = (self.username, self.password)
        self.page_size = page_size
        self.max_retries = max_retries
        self.timeout = timeout
        self._cursor: Optional[str] = None
        self._buffer: Deque[Dict[str, float]] = deque()
        self._current: Optional[Dict[str, float]] = None
        self._rate_limiter = _RateLimiter(rate_limit_per_minute, 60.0)
        self._refill()

    def quote(self) -> float:
        if not self._current:
            self._refill()
        return float(self._current["price_gbp_per_mwh"])

    def advance(self, _now=None) -> None:
        if self._buffer:
            self._buffer.popleft()
        if not self._buffer:
            self._refill()
        self._current = self._buffer[0]

    # ------------------------------------------------------------------
    def _refill(self) -> None:
        page = self._fetch_page()
        if not page:
            raise RuntimeError("ICE feed returned no data")
        self._buffer.extend(page)
        self._current = self._buffer[0]

    def _fetch_page(self) -> List[Dict[str, float]]:
        url = f"{self.base_url}/marketdata/futures"
        params = {"symbol": self.symbol, "limit": self.page_size}
        if self._cursor:
            params["cursor"] = self._cursor
        for attempt in range(self.max_retries):
            self._rate_limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 1))
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                quotes: Iterable[Dict[str, float]] = payload.get("quotes") or payload.get("data") or []
                quotes = [self._normalise_quote(q) for q in quotes]
                self._cursor = payload.get("next_cursor") or payload.get("meta", {}).get("next_cursor")
                if not self._cursor:
                    self._cursor = None
                return quotes
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.max_retries - 1:
                    raise RuntimeError("ICE feed exhausted retries") from exc
                time.sleep(min(2 ** attempt, 2))
        return []

    @staticmethod
    def _normalise_quote(row: Dict[str, float]) -> Dict[str, float]:
        for key in ("price_gbp_per_mwh", "settlement", "last_price"):
            if key in row:
                return {"price_gbp_per_mwh": float(row[key])}
        raise ValueError("ICE payload missing price field")
