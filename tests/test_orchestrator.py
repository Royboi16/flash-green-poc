# tests/test_orchestrator.py
import sys
import types
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.metrics as metrics_module
import app.storage as storage
from app import orchestrator
from app.exchange import Fill
from app.strategy import QuoteSnapshot, select_route


class DummyCounter:
    def __init__(self) -> None:
        self.value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount


class DummyGauge(DummyCounter):
    def set(self, value: float) -> None:  # type: ignore[override]
        self.value = value


def _patch_db(monkeypatch, tmp_path):
    db_path = tmp_path / "orchestrator.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage, "_DB_PATH", db_path)
    storage._init_schema()
    storage._conn = None
    with storage.get_connection() as conn:
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM orders")
    return db_path


@pytest.fixture
def metrics(monkeypatch):
    stub = types.SimpleNamespace(
        cycle=DummyCounter(),
        profit_positive=DummyCounter(),
        profit_negative=DummyCounter(),
        spread=DummyGauge(),
        daily_loss=DummyGauge(),
        trades_blocked=DummyCounter(),
    )
    monkeypatch.setattr(orchestrator, "METRICS", stub)
    monkeypatch.setattr(metrics_module, "METRICS", stub)
    return stub


@pytest.fixture(autouse=True)
def reset_state(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path)
    orchestrator._daily_loss = 0.0
    orchestrator._current_day = date.today()
    monkeypatch.setattr(orchestrator.settings, "trading_enabled", True)
    monkeypatch.setattr(orchestrator.settings, "max_daily_loss_gbp", 10_000.0)
    monkeypatch.setattr(orchestrator.settings, "max_notional_per_trade", 1_000_000.0)
    monkeypatch.setattr(orchestrator.settings, "neg_threshold", 100.0)
    monkeypatch.setattr(orchestrator.settings, "spread_min", 1.0)
    monkeypatch.setattr(orchestrator.settings, "slippage_bp", 0.0)


class StaticPower:
    def __init__(self, quote_price: float):
        self.quote_price = quote_price
        self.advanced = 0

    def quote(self) -> float:
        return self.quote_price

    def advance(self) -> None:
        self.advanced += 1

    def buy(self, mwh: float, max_price: float) -> Fill:
        return Fill(mwh, self.quote_price)


class StaticFutures:
    def __init__(self, quote_price: float):
        self.quote_price = quote_price
        self.advanced = 0

    def quote(self) -> float:
        return self.quote_price

    def advance(self) -> None:
        self.advanced += 1

    def sell(self, mwh: float) -> Fill:
        return Fill(mwh, self.quote_price)


@pytest.mark.usefixtures("metrics")
def test_run_cycle_records_trade(monkeypatch):
    power = StaticPower(quote_price=10.0)
    futures = StaticFutures(quote_price=50.0)
    monkeypatch.setattr(orchestrator, "POWER", power)
    monkeypatch.setattr(orchestrator, "FUTURES", futures)

    executed = orchestrator.run_cycle()
    assert executed is True

    trades = storage.get_trades()
    assert len(trades) == 1

    plan = select_route(
        QuoteSnapshot(
            spot_price=power.quote_price,
            futures_price=futures.quote_price,
            slippage_bp=orchestrator.settings.slippage_bp,
        )
    )
    expected_qty = plan.qty_mwh
    expected_profit = plan.expected_profit

    trade = trades[0]
    assert trade["qty_mwh"] == pytest.approx(expected_qty)
    assert trade["spot_price"] == power.quote_price
    assert trade["fut_price"] == futures.quote_price

    totals = storage.get_pnl_totals()
    assert totals["net"] == pytest.approx(expected_profit)
    assert orchestrator.METRICS.profit_positive.value == pytest.approx(expected_profit)
    assert orchestrator.METRICS.daily_loss.value == 0


@pytest.mark.usefixtures("metrics")
def test_run_cycle_blocks_notional(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "max_notional_per_trade", 1.0)
    power = StaticPower(quote_price=5.0)
    futures = StaticFutures(quote_price=10.0)
    monkeypatch.setattr(orchestrator, "POWER", power)
    monkeypatch.setattr(orchestrator, "FUTURES", futures)

    executed = orchestrator.run_cycle()
    assert executed is False
    assert orchestrator.METRICS.trades_blocked.value == 1
    assert storage.get_trades() == []


@pytest.mark.usefixtures("metrics")
def test_run_cycle_respects_daily_loss_cap(monkeypatch):
    monkeypatch.setattr(orchestrator.settings, "max_daily_loss_gbp", 1.0)
    orchestrator._daily_loss = orchestrator.settings.max_daily_loss_gbp

    executed = orchestrator.run_cycle()

    assert executed is False
    assert orchestrator.METRICS.trades_blocked.value == 1
    assert storage.get_trades() == []
