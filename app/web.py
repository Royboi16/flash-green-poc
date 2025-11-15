# app/web.py
from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app import logger
from app.metrics import METRICS
from app.storage import (
    get_trades,
    get_open_orders,
    get_loan_events,
    get_loan_balances,
)
from fastapi.responses import PlainTextResponse

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


class LoanEventOut(BaseModel):
    id: int
    reference: Optional[str]
    event_type: str
    asset: str
    amount: float
    fee_bps: float
    tx_hash: Optional[str]
    chain_id: Optional[int]
    metadata: Optional[dict]
    timestamp: datetime

    class Config:
        from_attributes = True


class LoanBalanceOut(BaseModel):
    asset: str
    outstanding: float
    updated_at: datetime

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
    return get_trades(limit)


@api.get("/orders/open", response_model=List[OrderOut])
async def open_orders():
    """
    List any in-flight (open) orders.
    """
    try:
        return get_open_orders()
    except Exception as e:
        # log full traceback
        logger.error("Error in /orders/open", exc_info=True)
        # return a plain-text 500 so the client sees something legible
        return PlainTextResponse(
            "Internal Server Error fetching open orders", status_code=500
        )

@api.get("/loans/events", response_model=List[LoanEventOut])
async def loan_events(limit: int = 100):
    """Loan drawdown/repayment audit log."""
    return get_loan_events(limit)


@api.get("/loans/balances", response_model=List[LoanBalanceOut])
async def loan_balances():
    """Outstanding balances per loan asset."""
    return get_loan_balances()
