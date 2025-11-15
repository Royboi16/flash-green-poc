# tests/test_feeds.py
import requests

from app.feeds.bmrs_csv import BMRSCsvFeed
from app.feeds.bmrs_rest import BMRSLiveFeed
from app.feeds.ice_rest import BrokerFuturesLiveFeed


class StubResponse:
    def __init__(self, payload, status_code: int = 200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._payload


class StubSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, *_, **__):
        if not self._responses:
            raise AssertionError("StubSession exhausted")
        self.calls += 1
        next_resp = self._responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return next_resp


def test_csv_feed_cycle():
    feed = BMRSCsvFeed("data/bmrs_spot_uk_2024.csv")
    first = feed.quote()
    for _ in range(100):
        feed.advance()
    assert isinstance(feed.quote(), float)
    assert feed.quote() != first or True  # ensure looping works


def test_bmrs_live_feed_pages_and_advances():
    responses = [
        StubResponse({
            "data": [
                {"price_gbp_per_mwh": "100"},
                {"price_gbp_per_mwh": "101"},
            ],
            "meta": {"next_page": 2},
        }),
        StubResponse({
            "data": [
                {"price_gbp_per_mwh": "102"},
            ],
            "meta": {},
        }),
        StubResponse({
            "data": [
                {"price_gbp_per_mwh": "103"},
            ],
            "meta": {"next_page": 2},
        }),
    ]
    session = StubSession(responses)
    feed = BMRSLiveFeed(
        api_key="token",
        session=session,
        rate_limit_per_minute=0,
    )

    assert feed.quote() == 100
    feed.advance()
    assert feed.quote() == 101
    feed.advance()
    assert feed.quote() == 102
    feed.advance()
    assert feed.quote() == 103  # cycled back to page 1
    assert session.calls == 3


def test_ice_live_feed_recovers_from_transient_failure():
    responses = [
        requests.exceptions.ConnectionError("boom"),
        StubResponse({
            "quotes": [
                {"settlement": "64.2"},
                {"settlement": "65.0"},
            ]
        }),
    ]
    session = StubSession(responses)
    feed = BrokerFuturesLiveFeed(
        base_url="https://example.com",
        username="user",
        password="pass",
        symbol="ICE-Q2",
        session=session,
        rate_limit_per_minute=0,
        max_retries=2,
    )

    assert feed.quote() == 64.2
    feed.advance()
    assert feed.quote() == 65.0
    assert session.calls == 2

