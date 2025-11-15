from contextlib import contextmanager

import pytest

from app import orchestrator
from app.exchange import Fill
from app.storage import Order, get_open_orders, init_db, save_order


@contextmanager
def dummy_flash_loan(*_, **__):
    wallet = {"gbp": 100_000.0}
    yield wallet


def _patch_common(monkeypatch, tmp_path, use_ice=True):
    init_db(tmp_path / "orch.db")
    monkeypatch.setattr(orchestrator, "FlashLoanAdapter", dummy_flash_loan)
    monkeypatch.setattr(orchestrator.settings, "use_ice_live", use_ice)

    called = {"value": False}

    def fake_should_trade(*_args, **_kwargs):
        called["value"] = True
        return False, 0.0, 0.0

    monkeypatch.setattr(orchestrator, "should_trade", fake_should_trade)
    return called


def test_run_cycle_requeues_partials(monkeypatch, tmp_path):
    called = _patch_common(monkeypatch, tmp_path)

    save_order(
        Order(
            id="legacy-order",
            symbol=orchestrator.settings.ice_symbol or "UK_BASE",
            side="BUY",
            qty_requested=10.0,
            status="PENDING",
        )
    )

    class StubICE:
        def __init__(self):
            self.buy_calls = []
            self.quote_price = 40.0

        def advance(self):
            return None

        def quote(self):
            return self.quote_price

        def buy(self, qty, max_price):
            self.buy_calls.append((qty, max_price))
            return Fill(qty_mwh=qty, price=max_price, order_id=f"retry-{len(self.buy_calls)}")

        def _fetch_order(self, order_id):
            return {
                "id": order_id,
                "status": "REJECTED",
                "filled_qty": 4.0,
                "avg_price": 45.0,
                "executions": [
                    {"qty": 4.0, "price": 45.0, "timestamp": "2024-01-01T00:00:00Z"}
                ],
                "cancel_reason": "timeout",
                "error": None,
                "is_active": False,
            }

        def cancel_order(self, order_id):
            return None

    stub = StubICE()
    monkeypatch.setattr(orchestrator, "pl", stub)

    class StubFuture:
        def advance(self):
            return None

        def quote(self):
            return 55.0

        def sell(self, qty):
            return Fill(qty_mwh=qty, price=55.0)

    monkeypatch.setattr(orchestrator, "ice", StubFuture())

    assert orchestrator.run_cycle() is False
    assert called["value"] is False, "new trades should not run while requeues happen"
    assert len(stub.buy_calls) == 1
    assert stub.buy_calls[0][1] > 45.0  # price bump applied
    open_orders = get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].status == "PENDING"


def test_run_cycle_rejected_buy_skips_short(monkeypatch, tmp_path):
    init_db(tmp_path / "orch2.db")
    monkeypatch.setattr(orchestrator, "FlashLoanAdapter", dummy_flash_loan)
    monkeypatch.setattr(orchestrator.settings, "use_ice_live", True)

    def trade_once(*_args, **_kwargs):
        return True, 5.0, 10.0

    monkeypatch.setattr(orchestrator, "should_trade", trade_once)

    class StubICE:
        def __init__(self):
            self.quote_price = 50.0

        def advance(self):
            return None

        def quote(self):
            return self.quote_price

        def buy(self, qty, max_price):
            return Fill(
                qty_mwh=0.0,
                price=max_price,
                order_id="o-1",
                status="REJECTED",
                error="ice error",
            )

        def _fetch_order(self, order_id):
            raise AssertionError("no settlement expected in same tick")

    stub_pl = StubICE()
    monkeypatch.setattr(orchestrator, "pl", stub_pl)

    class StubFuture:
        def __init__(self):
            self.sell_called = False

        def advance(self):
            return None

        def quote(self):
            return 55.0

        def sell(self, *_args, **_kwargs):
            self.sell_called = True
            raise AssertionError("future leg should not run after rejection")

    stub_future = StubFuture()
    monkeypatch.setattr(orchestrator, "ice", stub_future)

    assert orchestrator.run_cycle() is False
    assert get_open_orders(), "rejected order should be tracked for settlement"
    assert stub_future.sell_called is False
