# tests/test_orchestrator.py
import importlib
import sys

import pytest

from app.orchestrator import run_cycle

def test_pnl_positive():
    for _ in range(100):
        if run_cycle():
            break
    else:
        pytest.skip("No trade fired")

    # scrape prometheus or patch METRICS to assert profit > 0


def test_web3_adapter_receives_rpc(monkeypatch):
    monkeypatch.setenv("USE_WEB3_LOAN", "1")
    monkeypatch.setenv("FLASH_LOAN_RECEIVER", "0xReceiver")
    monkeypatch.setenv("RECEIVER_ADDRESS", "0xReceiver")
    monkeypatch.setenv("FLASH_LOAN_CONTRACT", "0xLender")
    monkeypatch.setenv("LENDER_KEY", "0x1234")
    monkeypatch.setenv("HARDHAT_RPC", "http://example-rpc:8545")

    # ensure orchestrator reloads with the updated env
    sys.modules.pop("app.orchestrator", None)
    sys.modules.pop("app.config", None)
    config = importlib.import_module("app.config")
    config.get_settings.cache_clear()
    config.settings = config.get_settings()
    orchestrator = importlib.import_module("app.orchestrator")

    class DummyFeed:
        def advance(self):
            pass

        def quote(self):
            return 10.0

    orchestrator.pl = DummyFeed()
    orchestrator.ice = DummyFeed()

    monkeypatch.setattr(orchestrator, "should_trade", lambda *_: (True, 1.0, 1.0))

    captured = {}

    class DummyLoan:
        def __init__(self, lender_address, private_key, rpc_url):
            captured["params"] = {
                "lender_address": lender_address,
                "private_key": private_key,
                "rpc_url": rpc_url,
            }

        def flash_loan(self, **_):
            return {"status": "ok"}

    monkeypatch.setattr(orchestrator, "FlashLoanAdapter", DummyLoan)

    assert orchestrator.run_cycle() is True
    assert str(captured["params"]["rpc_url"]) == str(orchestrator.settings.hardhat_rpc)
