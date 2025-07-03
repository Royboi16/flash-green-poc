# app/web.py

from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from app.metrics import METRICS
from app.storage import get_trades
from app.storage import get_open_orders, get_all_orders

api = FastAPI(
    title="Flash-Green PoC",
    version="0.1.0",
    docs_url="/",
    redoc_url=None,
)

@api.get("/healthz")
async def health():
    return {"status": "ok"}

@api.get("/pnl")
async def pnl():
    return {
        "profit": METRICS.profit_positive._value.get(),
        "loss":   METRICS.profit_negative._value.get(),
    }

@api.get("/metrics")
async def prom():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@api.get("/trades")
async def trades(limit: int = 100):
    """
    Retrieve up to `limit` most recent trades as returned by get_trades().
    """
    all_trades = get_trades()            # returns List[dict]
    # return the last `limit` entries (most recent)
    return all_trades[-limit:]
    
@api.get("/orders/open", response_model=List[OrderOut])
async def orders_open():
    return get_open_orders()

@api.get("/orders", response_model=List[OrderOut])
async def orders_all(limit: int = 100):
    return get_all_orders(limit)