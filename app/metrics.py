# app/metrics.py
from prometheus_client import Counter, Gauge

# just define metrics, server start happens elsewhere

METRICS = type("T", (), {})()
METRICS.cycle = Counter("cycles_total", "Total cycles run")
METRICS.profit_positive = Counter(
    "gbp_profit_positive",
    "Cumulative £ profit (positive ticks)",
)
METRICS.profit_negative = Counter(
    "gbp_profit_negative",
    "Cumulative £ loss (negative ticks)",
)
METRICS.spread = Gauge("last_spread", "Latest £/MWh spread")

# Phase 4: risk & limits
METRICS.daily_loss = Gauge(
    "gbp_daily_loss_total",
    "Cumulative daily loss in GBP",
)
METRICS.trades_blocked = Counter(
    "trades_blocked_by_limit_total",
    "Number of trades blocked by risk limits",
)
