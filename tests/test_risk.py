import pytest
from datetime import date
from app.orchestrator import run_cycle, _current_day, _daily_loss, _today
from app.config import settings
from datetime import timedelta

def test_notional_block(monkeypatch):
    # force a trade signal
    monkeypatch.setattr("app.orchestrator.should_trade", lambda s,f: (True, 2.0, 0.0))
    # set spot high so notional > cap
    monkeypatch.setattr("app.orchestrator.pl.quote", lambda: 10_000.0)
    settings.max_notional_per_trade = 1.0  # cap at £1
    # should return False and block
    assert run_cycle() is False

def test_daily_loss_reset(monkeypatch):
    import app.orchestrator as orch
    # simulate a loss inside the orchestrator module
    orch._daily_loss   = 600.0
    orch._current_day  = orch._today()
    # next day: override our helper to simulate tomorrow
    monkeypatch.setattr(
        orch,
        "_today",
        lambda: orch._current_day + timedelta(days=1)
    )
    # now run cycle with no trade signal
    monkeypatch.setattr("app.orchestrator.should_trade", lambda s,f: (False,0,0))
    assert run_cycle() is False
    # daily_loss should have reset to 0
    assert orch._daily_loss == 0.0

def test_trading_enabled_switch(monkeypatch):
    settings.trading_enabled = False
    # should immediately return False
    assert run_cycle() is False
    settings.trading_enabled = True

