# app/web.py
from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app import logger
from app.config import settings
from app.metrics import METRICS
from app.storage import (
    get_cash_balances,
    get_open_orders,
    get_positions,
    get_risk_events,
    get_trades,
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
    fx_currency: str
    counterparty_id: str

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
    fx_currency: str
    counterparty_id: str

    class Config:
        from_attributes = True


class PositionOut(BaseModel):
    symbol: str
    qty_mwh: float
    avg_price: float
    fx_currency: str
    counterparty_id: str
    updated_at: datetime

    class Config:
        from_attributes = True


class CashBalanceOut(BaseModel):
    account_id: str
    currency: str
    balance: float
    counterparty_id: str
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskEventOut(BaseModel):
    id: Optional[int]
    event_type: str
    severity: str
    description: str
    counterparty_id: str
    fx_currency: str
    exposure: float
    created_at: datetime

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


@api.get("/positions", response_model=List[PositionOut])
async def positions():
    """Expose the latest internal positions for reconciliation."""

    return get_positions()


@api.get("/cash/balances", response_model=List[CashBalanceOut])
async def cash_balances():
    """Surface cash ledgers for controllers."""

    return get_cash_balances()


@api.get("/risk/events", response_model=List[RiskEventOut])
async def risk_events(limit: int = 100):
    """Return recent risk-limit events."""

    return get_risk_events(limit)


@api.get("/limits")
async def limits_state():
    """Provide limit configuration and live exposure state."""

    return {
        "trading_enabled": settings.trading_enabled,
        "max_notional_per_trade": settings.max_notional_per_trade,
        "max_daily_loss_gbp": settings.max_daily_loss_gbp,
        "current_daily_loss_gbp": METRICS.daily_loss._value.get(),
        "open_exposure_gbp": METRICS.open_exposure_gbp._value.get(),
    }