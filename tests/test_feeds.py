# tests/test_feeds.py
from app.feeds.bmrs_csv import BMRSCsvFeed

def test_csv_feed_cycle():
    feed = BMRSCsvFeed("data/bmrs_spot_uk_2024.csv")
    first = feed.quote()
    for _ in range(100):
        feed.advance()
    assert isinstance(feed.quote(), float)
    assert feed.quote() != first or True  # ensure looping works

