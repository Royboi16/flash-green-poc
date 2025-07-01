# app/web.py
from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from app import logger
from app.metrics import METRICS
from typing import List
from app.storage import get_trades
from pydantic import BaseModel
from datetime import datetime
from app.storage import get_trades, Trade as TradeRow

api = FastAPI(title="Flash‑Green PoC",
              version="0.1.0",
              docs_url="/",
              redoc_url=None)
              
class TradeOut(BaseModel):
    id: int
    timestamp: datetime
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float

    class Config:
        orm_mode = True

@api.get("/healthz")
async def health():
    return {"status": "ok"}

@api.get("/pnl")
async def pnl():
    return {
        "profit": METRICS.profit_positive._value.get(),
        "loss": METRICS.profit_negative._value.get(),
    }

@api.get("/metrics")
async def prom():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
    
@api.get("/trades", response_model=List[TradeOut])
async def trades(limit: int = 100):
    """
    Retrieve up to `limit` most recent trades.
    """
    rows = get_trades(limit)
    # pydantic will automatically convert our TradeRow dataclasses
    return rows
