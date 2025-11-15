# app/metrics.py
from prometheus_client import Counter, Gauge

# just define metrics, server start happens elsewhere

METRICS = type("T", (), {})()
METRICS.cycle  = Counter("cycles_total", "Total cycles run")
METRICS.profit_positive = Counter("gbp_profit_positive",
                                  "Cumulative £ profit (positive ticks)")
METRICS.profit_negative = Counter("gbp_profit_negative",
                                  "Cumulative £ loss (negative ticks)")
METRICS.spread = Gauge("last_spread", "Latest £/MWh spread")
METRICS.power_latency_ms = Gauge(
    "power_exchange_latency_ms",
    "Last observed latency talking to the Power exchange (ms)",
)
METRICS.ice_latency_ms = Gauge(
    "ice_exchange_latency_ms",
    "Last observed latency talking to ICE (ms)",
)
METRICS.flash_loan_latency_ms = Gauge(
    "flash_loan_latency_ms",
    "Latency to acquire flash-loan liquidity (ms)",
)
METRICS.power_api_failures = Counter(
    "power_exchange_failures_total",
    "Number of Power exchange API failures",
)
METRICS.ice_api_failures = Counter(
    "ice_exchange_failures_total",
    "Number of ICE API failures",
)
METRICS.flash_loan_failures = Counter(
    "flash_loan_failures_total",
    "Number of flash-loan adapter failures",
)
METRICS.open_exposure_gbp = Gauge(
    "open_exposure_gbp",
    "Gross open exposure awaiting settlement (GBP)",
)

# Phase 4: risk & limits
METRICS.daily_loss      = Gauge("gbp_daily_loss_total",      "Cumulative daily loss in GBP")
METRICS.trades_blocked  = Counter("trades_blocked_by_limit_total",
                                  "Number of trades blocked by risk limits")