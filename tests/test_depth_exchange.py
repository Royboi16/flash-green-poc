import time

from app.exchange import DepthAwarePowerExchange


def test_depth_buy_latency_slippage(monkeypatch):
    exp_latency = 100
    exp_slip = 50  # 50 bp = 0.5%
    de = DepthAwarePowerExchange(
        latency_ms=exp_latency,
        slippage_bp=exp_slip,
        levels=3,
        level_size=10,
    )

    monkeypatch.setattr(de.feed, "quote", lambda: 100.0)
    start = time.time()
    fill = de.buy(mwh=5, max_price=101.0)
    elapsed = (time.time() - start) * 1_000
    assert elapsed >= exp_latency
    assert 100.0 <= fill.price <= 100.5
