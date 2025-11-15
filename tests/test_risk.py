from datetime import timedelta

from app.config import settings
import app.orchestrator as orch
from app.orchestrator import run_cycle


def test_notional_block(monkeypatch):
    monkeypatch.setattr(
        "app.orchestrator.should_trade",
        lambda *_: (True, 2.0, 0.0),
    )
    monkeypatch.setattr("app.orchestrator.POWER.quote", lambda: 10_000.0)
    settings.max_notional_per_trade = 1.0
    assert run_cycle() is False


def test_daily_loss_reset(monkeypatch):
    orch._daily_loss = 600.0
    orch._current_day = orch._today()
    monkeypatch.setattr(
        orch,
        "_today",
        lambda: orch._current_day + timedelta(days=1),
    )
    monkeypatch.setattr(
        "app.orchestrator.should_trade",
        lambda *_: (False, 0, 0),
    )
    assert run_cycle() is False
    assert orch._daily_loss == 0.0


def test_trading_enabled_switch():
    settings.trading_enabled = False
    assert run_cycle() is False
    settings.trading_enabled = True
