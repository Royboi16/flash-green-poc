# tests/test_spread.py
from app.strategy import should_trade

def test_trigger():
    assert should_trade(-5, 70)[0]      # neg spot, big spread → trade
    assert not should_trade(10, 68)[0]  # spot > 0 → skip

