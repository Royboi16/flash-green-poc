from datetime import date, datetime
import types

import pytest

import app.db as db
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


def _patch_db():
    engine = db.override_engine("sqlite:///:memory:")
    storage.Base.metadata.create_all(engine)
    return engine


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
def reset_state(monkeypatch):
    _patch_db()
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
    expected_profit = plan.qty_mwh * (futures.quote_price - power.quote_price)

    assert plan.expected_profit == pytest.approx(expected_profit)

    trade = trades[0]
    assert trade["qty_mwh"] == pytest.approx(expected_qty)
    assert trade["spot_price"] == power.quote_price
    assert trade["fut_price"] == futures.quote_price

    totals = storage.get_pnl_totals()
    assert totals["net"] == pytest.approx(expected_profit)
    assert orchestrator.METRICS.profit_positive.value == pytest.approx(expected_profit)
    assert orchestrator.METRICS.daily_loss.value == 0


@pytest.mark.usefixtures("metrics")
def test_record_trade_negative_spread():
    fill_a = Fill(qty_mwh=5.0, price=50.0)
    fill_b = Fill(qty_mwh=5.0, price=10.0)

    profit = orchestrator._record_trade(
        fill_a,
        fill_b,
        qty=5.0,
        spot=fill_a.price,
        fut=fill_b.price,
    )

    trades = storage.get_trades()
    assert len(trades) == 1
    assert trades[0]["profit"] == pytest.approx(profit)

    assert profit == pytest.approx(-200.0)
    assert orchestrator.METRICS.profit_negative.value == pytest.approx(200.0)
    assert orchestrator._daily_loss == pytest.approx(200.0)
    assert orchestrator.METRICS.daily_loss.value == pytest.approx(200.0)


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
