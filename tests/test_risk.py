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
    settings.max_notional_per_trade = 1_000_000.0


def test_daily_loss_cap(monkeypatch):
    settings.trading_enabled = True
    settings.max_daily_loss_gbp = 100.0

    orch._current_day = orch._today()
    orch._daily_loss = 50.0

    blocked_start = orch.METRICS.trades_blocked._value.get()

    def fake_should_trade(*_):
        return True, 1.0, 0.0

    class Fill:
        def __init__(self, price: float):
            self.order_id = "1"
            self.qty_mwh = 1.0
            self.price = price

    monkeypatch.setattr("app.orchestrator.should_trade", fake_should_trade)
    monkeypatch.setattr("app.orchestrator.POWER.quote", lambda: 10_000.0)
    monkeypatch.setattr("app.orchestrator.FUTURES.quote", lambda: 9_999.0)
    monkeypatch.setattr("app.orchestrator.POWER.buy", lambda *_, **__: Fill(-20.0))
    monkeypatch.setattr("app.orchestrator.FUTURES.sell", lambda *_, **__: Fill(-30.0))
    monkeypatch.setattr("app.orchestrator.save_order", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.orchestrator.save_trade", lambda *_args, **_kwargs: None)

    assert run_cycle() is True
    assert orch._daily_loss == 100.0

    call_count = {"calls": 0}

    def should_not_run(*_):
        call_count["calls"] += 1
        return True, 1.0, 0.0

    monkeypatch.setattr("app.orchestrator.should_trade", should_not_run)

    assert run_cycle() is False
    assert call_count["calls"] == 0
    assert orch.METRICS.trades_blocked._value.get() == blocked_start + 1
