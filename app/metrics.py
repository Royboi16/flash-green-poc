# app/metrics.py
from prometheus_client import Counter, Gauge, start_http_server
start_http_server(8000)

METRICS = type("T", (), {})()
METRICS.cycle  = Counter("cycles_total", "Total cycles run")
METRICS.profit = Counter("gbp_profit", "Cumulative £ profit")
METRICS.spread = Gauge("last_spread", "Latest £/MWh spread")

