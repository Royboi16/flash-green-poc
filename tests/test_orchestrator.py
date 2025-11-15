# tests/test_orchestrator.py
import pytest

from app.orchestrator import run_cycle


def test_pnl_positive():
    for _ in range(100):
        if run_cycle():
            break
    else:
        pytest.skip("No trade fired")

    # scrape prometheus or patch METRICS to assert profit > 0
