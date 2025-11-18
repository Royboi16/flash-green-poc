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
METRICS.order_settlement_skipped = Counter(
    "order_settlement_skipped_total",
    "Open orders skipped during settlement",
)
METRICS.order_settlement_failures = Counter(
    "order_settlement_failures_total",
    "Failed attempts to settle open orders",
)

# Fnality/HQLAˣ atomic repo flash-loan path
METRICS.flash_repo_attempts = Counter(
    "flash_repo_attempts_total",
    "Number of Fnality/HQLAˣ repo attempts",
)
METRICS.flash_repo_commits = Counter(
    "flash_repo_commits_total",
    "Successful Fnality/HQLAˣ atomic repo commits",
)
METRICS.flash_repo_failures = Counter(
    "flash_repo_failures_total",
    "Failed Fnality/HQLAˣ repo submissions",
)
METRICS.flash_repo_rollbacks = Counter(
    "flash_repo_rollbacks_total",
    "Rollbacks triggered after repo commit failures",
)
METRICS.trade_partial_failures = Counter(
    "trade_partial_failures_total",
    "Cases where one leg succeeded but persistence or hedging failed",
)

# Phase 4: risk & limits
METRICS.daily_loss = Gauge(
    "gbp_daily_loss_total",
    "Cumulative daily loss in GBP",
)
METRICS.trades_blocked = Counter(
    "trades_blocked_by_limit_total",
    "Number of trades blocked by risk limits",
)
