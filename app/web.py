# app/web.py
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.logger import logger
from app.metrics import METRICS
from app.storage import get_open_orders, get_trades

api = FastAPI(
    title="Flash-Green PoC",
    version="0.1.0",
    docs_url="/",
    redoc_url=None,
)

# ─── Models for serialization ────────────────────────────────────────────────


class TradeOut(BaseModel):
    id: int
    timestamp: datetime
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: Optional[str]
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str

    class Config:
        from_attributes = True


# ─── Health & metrics ────────────────────────────────────────────────────────


@api.get("/healthz")
async def health():
    return {"status": "ok"}


@api.get("/metrics")
async def prom():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@api.get("/pnl")
async def pnl():
    return {
        "profit": METRICS.profit_positive._value.get(),
        "loss": METRICS.profit_negative._value.get(),
    }


# ─── Data endpoints ──────────────────────────────────────────────────────────


@api.get("/trades", response_model=List[TradeOut])
async def trades(limit: int = 100):
    """
    Retrieve up to `limit` most recent trades.
    """
    return get_trades(limit=limit)


@api.get("/orders/open", response_model=List[OrderOut])
async def open_orders():
    """
    List any in-flight (open) orders.
    """
    try:
        return get_open_orders()
    except Exception:
        # log full traceback
        logger.error("Error in /orders/open", exc_info=True)
        # return a plain-text 500 so the client sees something legible
        return PlainTextResponse(
            "Internal Server Error fetching open orders", status_code=500
        )
