# app/storage.py

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, NamedTuple

from sqlalchemy import Column, DateTime, Float, Integer, String, case, func, select, update
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, get_session

# ─── Models ──────────────────────────────────────────────────────────────────


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qty_mwh = Column(Float, nullable=False)
    spot_price = Column(Float, nullable=False)
    fut_price = Column(Float, nullable=False)
    profit = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=False), index=True, nullable=False)
    repo_tx_hash = Column(String, nullable=True)
    repo_cash_token = Column(String, nullable=True)
    repo_asset_token = Column(String, nullable=True)
    repo_timestamp = Column(DateTime(timezone=False), nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "qty_mwh": self.qty_mwh,
            "spot_price": self.spot_price,
            "fut_price": self.fut_price,
            "profit": self.profit,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "repo_tx_hash": self.repo_tx_hash,
            "repo_cash_token": self.repo_cash_token,
            "repo_asset_token": self.repo_asset_token,
            "repo_timestamp": self.repo_timestamp.isoformat()
            if self.repo_timestamp
            else None,
        }


class OrderRecord(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty_requested = Column(Float, nullable=False)
    qty_filled = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=False), nullable=False)


class Order(NamedTuple):
    id: str
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str
    timestamp: datetime


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _ensure_session(session: Session | None = None, conn: Session | None = None) -> tuple[Session, bool]:
    selected = session or conn
    if selected is not None:
        return selected, False
    return SessionLocal(), True


def _close_session(session: Session, owns: bool) -> None:
    if owns:
        session.close()


# ─── Trade persistence ───────────────────────────────────────────────────────


def save_trade(
    qty_mwh: float,
    spot_price: float,
    fut_price: float,
    profit: float,
    repo_tx_hash: str | None = None,
    repo_cash_token: str | None = None,
    repo_asset_token: str | None = None,
    repo_timestamp: str | datetime | None = None,
    session: Session | None = None,
    conn: Session | None = None,
) -> None:
    """Persist a completed trade (used by your PoC)."""

    trade_ts = datetime.utcnow()
    repo_ts = _coerce_datetime(repo_timestamp)
    db_session, owns_session = _ensure_session(session, conn)
    try:
        db_session.add(
            Trade(
                qty_mwh=qty_mwh,
                spot_price=spot_price,
                fut_price=fut_price,
                profit=profit,
                timestamp=trade_ts,
                repo_tx_hash=repo_tx_hash,
                repo_cash_token=repo_cash_token,
                repo_asset_token=repo_asset_token,
                repo_timestamp=repo_ts,
            )
        )
        db_session.commit()
    finally:
        _close_session(db_session, owns_session)


def get_trades(
    limit: int | None = None,
    session: Session | None = None,
    conn: Session | None = None,
) -> List[Dict[str, Any]]:
    """Fetch past trades for your PnL API ordered by recency."""

    db_session, owns_session = _ensure_session(session, conn)
    try:
        stmt = select(Trade).order_by(Trade.timestamp.desc(), Trade.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        trades = db_session.scalars(stmt).all()
        return [trade.as_dict() for trade in trades]
    finally:
        _close_session(db_session, owns_session)


def get_pnl_totals(session: Session | None = None, conn: Session | None = None) -> Dict[str, float]:
    """Aggregate net, positive, and negative PnL from stored trades."""

    db_session, owns_session = _ensure_session(session, conn)
    try:
        stmt = select(
            func.coalesce(
                func.sum(case((Trade.profit >= 0, Trade.profit), else_=0)), 0
            ).label("positive"),
            func.coalesce(
                func.sum(case((Trade.profit < 0, -Trade.profit), else_=0)), 0
            ).label("negative"),
            func.coalesce(func.sum(Trade.profit), 0).label("net"),
        )
        row = db_session.execute(stmt).one()
        return {
            "positive": float(row.positive),
            "negative": float(row.negative),
            "net": float(row.net),
        }
    finally:
        _close_session(db_session, owns_session)


# ─── Order‐tracking / idempotency ────────────────────────────────────────────


def save_order(
    order: Order,
    session: Session | None = None,
    conn: Session | None = None,
) -> None:
    """Insert or replace an in‐flight ICE order."""

    db_session, owns_session = _ensure_session(session, conn)
    try:
        db_session.merge(
            OrderRecord(
                id=order.id,
                symbol=order.symbol,
                side=order.side,
                qty_requested=order.qty_requested,
                qty_filled=order.qty_filled,
                avg_price=order.avg_price,
                status=order.status,
                timestamp=_coerce_datetime(order.timestamp) or datetime.utcnow(),
            )
        )
        db_session.commit()
    finally:
        _close_session(db_session, owns_session)


def get_open_orders(
    session: Session | None = None,
    conn: Session | None = None,
) -> List[Order]:
    """Return all orders not yet FILLED/CANCELLED/REJECTED."""

    db_session, owns_session = _ensure_session(session, conn)
    try:
        stmt = select(OrderRecord).where(
            OrderRecord.status.notin_(
                ["FILLED", "CANCELLED", "REJECTED"]
            )
        )
        orders = db_session.scalars(stmt).all()
        return [
            Order(
                id=order.id,
                symbol=order.symbol,
                side=order.side,
                qty_requested=order.qty_requested,
                qty_filled=order.qty_filled,
                avg_price=order.avg_price,
                status=order.status,
                timestamp=order.timestamp,
            )
            for order in orders
        ]
    finally:
        _close_session(db_session, owns_session)


def update_order(
    order_id: str,
    filled: float,
    avg_price: float,
    status: str,
    session: Session | None = None,
    conn: Session | None = None,
) -> None:
    """Update status/filled/price for an existing order."""

    db_session, owns_session = _ensure_session(session, conn)
    try:
        stmt = (
            update(OrderRecord)
            .where(OrderRecord.id == order_id)
            .values(qty_filled=filled, avg_price=avg_price, status=status)
        )
        db_session.execute(stmt)
        db_session.commit()
    finally:
        _close_session(db_session, owns_session)


# ─── FastAPI dependency helper ───────────────────────────────────────────────


def connection_dependency() -> Iterator[Session]:
    """Yield a configured session for FastAPI dependencies."""

    with get_session() as session:
        yield session

# Keep backward-compatible alias
@contextmanager
def get_connection() -> Iterator[Session]:
    with get_session() as session:
        yield session

