"""BMRS REST market data adapter."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional

import requests

from .base import MarketAdapter


class _RateLimiter:
    """Simple token bucket style limiter for REST polling."""

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


class BMRSLiveFeed(MarketAdapter):
    """Paginated BMRS REST adapter used when ``settings.use_live_feed`` is enabled."""

    def __init__(
        self,
        api_key: str,
        dataset: str = "B1770",
        session: Optional[requests.Session] = None,
        page_size: int = 48,
        max_retries: int = 3,
        rate_limit_per_minute: int = 30,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("BMRS live feed requires an API key")
        self.api_key = api_key
        self.dataset = dataset
        self.base_url = "https://api.bmreports.com/BMRS"
        self.session = session or requests.Session()
        self.page_size = page_size
        self.max_retries = max_retries
        self.timeout = timeout
        self._rate_limiter = _RateLimiter(rate_limit_per_minute, 60.0)
        self._buffer: Deque[Dict[str, float]] = deque()
        self._next_page: int = 1
        self._current: Optional[Dict[str, float]] = None
        self._refill()

    # ------------------------------------------------------------------
    # MarketAdapter interface
    # ------------------------------------------------------------------
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
            raise RuntimeError("BMRS feed returned no market data")
        self._buffer.extend({"price_gbp_per_mwh": float(row["price_gbp_per_mwh"])} for row in page)
        self._current = self._buffer[0]

    def _fetch_page(self) -> List[Dict[str, float]]:
        url = f"{self.base_url}/{self.dataset}/v1"
        params = {
            "APIKey": self.api_key,
            "ServiceType": "json",
            "PageSize": self.page_size,
            "Page": self._next_page,
        }
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
                data: Iterable[Dict[str, float]] = payload.get("data") or payload.get("Data") or []
                data = list(data)
                next_page = payload.get("meta", {}).get("next_page") or payload.get("next_page")
                if next_page:
                    self._next_page = int(next_page)
                else:
                    # cycle back to first page if server gives no cursor
                    self._next_page = 1
                return [self._normalise_row(row) for row in data]
            except (requests.RequestException, ValueError) as exc:
                if attempt == self.max_retries - 1:
                    raise RuntimeError("BMRS feed exhausted retries") from exc
                time.sleep(min(2 ** attempt, 2))
        return []

    @staticmethod
    def _normalise_row(row: Dict[str, float]) -> Dict[str, float]:
        if "price_gbp_per_mwh" in row:
            return {"price_gbp_per_mwh": float(row["price_gbp_per_mwh"])}
        for key in ("price", "last_price", "spot"):
            if key in row:
                return {"price_gbp_per_mwh": float(row[key])}
        raise ValueError("BMRS payload missing price field")
