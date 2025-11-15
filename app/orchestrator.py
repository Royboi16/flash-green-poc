# app/orchestrator.py
"""
Drives a single arbitrage cycle and (if run as __main__)
loops forever once every second.
"""

import os
from datetime import datetime, date
from time import sleep
from uuid import uuid4

from app.logger import logger
from app.metrics import METRICS
from app.strategy import should_trade
from app.storage import (
    save_trade,
    get_open_orders,
    save_order,
    update_order,
    record_loan_drawdown,
    record_loan_repayment,
    Order,
)
from app.config import settings

# ─── choose PowerExchange implementation ───────────────────────────────────
if settings.use_ice_live:
    from app.exchange_ice import ICEPowerExchange as PowerExchange
elif settings.use_depth_sim:
    from app.exchange import DepthAwarePowerExchange as PowerExchange
else:
    from app.exchange import PowerCsvExchange as PowerExchange

# instantiate pl
if settings.use_ice_live:
    pl = PowerExchange()
elif settings.use_depth_sim:
    pl = PowerExchange(
        settings.exec_latency_ms,
        settings.slippage_bp,
        settings.book_levels,
        settings.book_size_mwh,
    )
else:
    pl = PowerExchange()

# futures always CSV for now
from app.exchange import IceCsvExchange
ice = IceCsvExchange()

# flash-loan adapter (unchanged)
if os.getenv("USE_WEB3_LOAN") == "1":
    from app.loan_web3 import Web3FlashLoan as FlashLoanAdapter
else:
    from app.loan import flash_loan as FlashLoanAdapter

# ── Allow test-friendly override of “today” ────────────────────────────────
def _today() -> date:
    return date.today()

# Globals to track daily PnL
_current_day: date = _today()
_daily_loss:   float = 0.0


def _new_loan_reference() -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    return f"loan-{stamp}-{uuid4().hex[:8]}"

def _settle_open_orders(pl):
    for o in get_open_orders():
        data = pl._fetch_order(o.id)
        stat = data["status"]
        filled = float(data.get("filled_qty", 0))
        avg_p = float(data.get("avg_price", 0))
        # ←── ADD YOUR DEBUG LOG HERE ─────────────────────────────
        # ── DEBUG: show what we're settling ────────────────────────────────
        logger.debug(f"Settling order {o.id}: status={stat}, filled={filled}, avg_price={avg_p}")
        update_order(o.id, filled, avg_p, stat)

def run_cycle() -> bool:
    global _current_day, _daily_loss
    
    # ——— DEBUG: show current configuration —————————————————————————
    logger.debug(
        f"CONFIG: neg_threshold={settings.neg_threshold!r}, "
        f"spread_min={settings.spread_min!r}, "
        f"max_notional_per_trade={settings.max_notional_per_trade!r}"
    )

    # reset daily loss at UTC midnight
    today = _today()
    if today != _current_day:
        _current_day = today
        _daily_loss   = 0.0
        METRICS.daily_loss.set(_daily_loss)

    # if using live ICE, reconcile any in-flight orders first
    if settings.use_ice_live:
        _settle_open_orders(pl)
        # if any still open, wait
        if get_open_orders():
            logger.info("Open orders pending, skipping this tick")
            return False

    # master switch
    if not settings.trading_enabled:
        METRICS.trades_blocked.inc()
        return False

    # advance both feeds each tick
    now = datetime.utcnow()
    pl.advance()
    ice.advance()

    spot = pl.quote()
    fut  = ice.quote()
    logger.debug(f"TICK:   spot={spot!r}, fut={fut!r}, spread={fut-spot!r}")

    trade, qty, spread = should_trade(spot, fut)
    METRICS.spread.set(spread)
    logger.debug(f" SIGNAL: trade={trade!r}, qty={qty!r}, spread={spread!r}")
    
    logger.debug(f"DEBUG tick: spot={spot}, fut={fut}, spread={spread}, trade={trade}, qty={qty}")
    
    if not trade:
        return False

    # notional check (qty×spot gives £ exposure)
    notional = qty * spot
    if notional > settings.max_notional_per_trade:
        logger.warning(
            f"Notional £{notional:.2f} > cap £{settings.max_notional_per_trade}"
        )
        METRICS.trades_blocked.inc()
        return False

    loan_amount = settings.loan_size_gbp
    fee_gbp = loan_amount * settings.loan_fee_bps / 10_000
    repayment_total = loan_amount + fee_gbp
    repayment_assets = list(settings.loan_repayment_assets or [settings.loan_principal_asset])

    # ── On‐chain flash‐loan branch ─────────────────────────────────────────────
    if os.getenv("USE_WEB3_LOAN") == "1":
        if not settings.receiver_address:
            raise RuntimeError(
                "USE_WEB3_LOAN=1 but FLASH_LOAN_RECEIVER is not set"
            )
        if not settings.flash_loan_contract:
            raise RuntimeError(
                "USE_WEB3_LOAN=1 but FLASH_LOAN_CONTRACT is not set"
            )
        private_key = os.getenv("LENDER_KEY")
        if not private_key:
            raise RuntimeError("USE_WEB3_LOAN=1 but LENDER_KEY is missing")

        rpc_url = settings.rpc_url_for_network()
        loan = FlashLoanAdapter(
            lender_address=settings.flash_loan_contract,
            private_key=private_key,
            network=settings.flash_loan_network,
            rpc_url=rpc_url,
        )
        reference = _new_loan_reference()
        record_loan_drawdown(
            asset=settings.loan_principal_asset,
            amount=loan_amount,
            fee_bps=settings.loan_fee_bps,
            reference=reference,
            metadata={"mode": "web3", "network": settings.flash_loan_network},
        )
        amount_wei = int(loan_amount * (10 ** settings.loan_asset_decimals))
        meta, decoded_event = loan.flash_loan(
            receiver_address=settings.receiver_address,
            amount_wei=amount_wei,
            expected_fee_bps=settings.loan_fee_bps,
        )
        record_loan_repayment(
            asset=settings.loan_principal_asset,
            amount=repayment_total,
            fee_bps=settings.loan_fee_bps,
            reference=reference,
            tx_hash=meta["transactionHash"],
            chain_id=loan.chain_id,
            metadata={"event": decoded_event, **meta},
        )
        return True

    # ── Mock flash‐loan branch ─────────────────────────────────────────────────
    else:
        with FlashLoanAdapter(
            limit_gbp=loan_amount,
            principal_asset=settings.loan_principal_asset,
            repayment_assets=repayment_assets,
        ) as wallet:
            try:
                reference = _new_loan_reference()
                record_loan_drawdown(
                    asset=settings.loan_principal_asset,
                    amount=loan_amount,
                    fee_bps=settings.loan_fee_bps,
                    reference=reference,
                    metadata={"mode": "sim"},
                )
                cash_balance = loan_amount
                # Leg A – buy power at current spot price cap
                try:
                    fill_a = pl.buy(qty, max_price=spot)
                except RuntimeError:
                    # If we still slip, skip this tick
                    return False

                # ── Record the ICE buy order for idempotency ────────────────────
                save_order(Order(
                    id=fill_a.order_id,
                    timestamp=datetime.utcnow(),
                    symbol=settings.ice_symbol,
                    side="BUY",
                    qty_requested=qty,
                    qty_filled=fill_a.qty_mwh,
                    avg_price=fill_a.price,
                    status="PENDING",
                ))

                cash_balance -= fill_a.qty_mwh * fill_a.price

                # Leg B – short Baseload future
                fill_b = ice.sell(qty)
                cash_balance += fill_b.qty_mwh * fill_b.price

                if cash_balance < repayment_total:
                    logger.error(
                        "Insufficient GBP to settle flash-loan: cash=%.2f required=%.2f",
                        cash_balance,
                        repayment_total,
                    )
                    METRICS.trades_blocked.inc()
                    return False

                # Record PnL
                profit = cash_balance - repayment_total
                if profit >= 0:
                    METRICS.profit_positive.inc(profit)
                else:
                    METRICS.profit_negative.inc(-profit)

                # track daily loss
                if profit < 0:
                    _daily_loss += -profit
                    METRICS.daily_loss.set(_daily_loss)

                record_loan_repayment(
                    asset=settings.loan_principal_asset,
                    amount=repayment_total,
                    fee_bps=settings.loan_fee_bps,
                    reference=reference,
                    metadata={"mode": "sim", "profit": profit},
                )

                save_trade(
                    qty_mwh=qty,
                    spot_price=spot,
                    fut_price=fut,
                    profit=profit,
                )

                return True

            finally:
                # ALWAYS repay principal before context exits
                for asset in set(repayment_assets + [settings.loan_principal_asset]):
                    wallet[asset] = 0.0

# ---------------------------------------------------------------------------
# Simple CLI loop
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from prometheus_client import start_http_server
    from app.config        import settings
    from app.logger        import logger
    import uvicorn
    from threading import Thread

    # start Prometheus exporter
    try:
        start_http_server(settings.metrics_port)
        logger.info(f"Prometheus metrics listening on {settings.metrics_port}")
    except OSError:
        logger.warning(
            f"Could not bind metrics port {settings.metrics_port}; skipping"
        )

    # helper to start FastAPI in a thread
    def _start_api():
        try:
            uvicorn.run(
                app="app.web:api",
                host="0.0.0.0",
                port=settings.api_port,
                log_level="warning",
            )
        except OSError as e:
            logger.warning(f"Could not bind API port {settings.api_port}: {e}")

    # launch FastAPI
    Thread(target=_start_api, daemon=True).start()
    logger.info(f"FastAPI health & Prom JSON on port {settings.api_port}")

    # main loop
    logger.info("Starting flash-green PoC loop …")
    while True:
        if run_cycle():
            logger.info("[green]✅  trade executed[/green]")
        sleep(1)