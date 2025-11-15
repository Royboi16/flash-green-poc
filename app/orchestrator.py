# app/orchestrator.py
"""Drive a single arbitrage cycle and loop forever when run as a CLI."""

import os
from datetime import date, datetime
from threading import Thread
from time import sleep

from app.config import settings
from app.logger import logger
from app.metrics import METRICS
from app.storage import (
    Order,
    get_open_orders,
    save_order,
    save_trade,
    update_order,
)
from app.strategy import should_trade

if settings.use_ice_live:
    from app.exchange_ice import ICEPowerExchange as PowerExchange
elif settings.use_depth_sim:
    from app.exchange import DepthAwarePowerExchange as PowerExchange
else:
    from app.exchange import PowerCsvExchange as PowerExchange

from app.exchange import IceCsvExchange

if settings.use_ice_live:
    POWER = PowerExchange()
elif settings.use_depth_sim:
    POWER = PowerExchange(
        settings.exec_latency_ms,
        settings.slippage_bp,
        settings.book_levels,
        settings.book_size_mwh,
    )
else:
    POWER = PowerExchange()

ICE = IceCsvExchange()

if os.getenv("USE_WEB3_LOAN") == "1":
    from app.loan_web3 import Web3FlashLoan as FlashLoanAdapter
else:
    from app.loan import flash_loan as FlashLoanAdapter


def _today() -> date:
    return date.today()


def _settle_open_orders() -> None:
    for order in get_open_orders():
        data = POWER._fetch_order(order.id)  # type: ignore[attr-defined]
        status = data["status"]
        filled = float(data.get("filled_qty", 0))
        avg_price = float(data.get("avg_price", 0))
        logger.debug(
            "Settling order %s: status=%s filled=%s avg_price=%s",
            order.id,
            status,
            filled,
            avg_price,
        )
        update_order(order.id, filled, avg_price, status)


_current_day: date = _today()
_daily_loss: float = 0.0


def run_cycle() -> bool:
    global _current_day, _daily_loss

    logger.debug(
        "CONFIG neg_threshold=%s spread_min=%s max_notional=%s",
        settings.neg_threshold,
        settings.spread_min,
        settings.max_notional_per_trade,
    )

    today = _today()
    if today != _current_day:
        _current_day = today
        _daily_loss = 0.0
        METRICS.daily_loss.set(_daily_loss)

    if settings.use_ice_live:
        _settle_open_orders()
        if get_open_orders():
            logger.info("Open orders pending, skipping this tick")
            return False

    if not settings.trading_enabled:
        METRICS.trades_blocked.inc()
        return False

    POWER.advance()
    ICE.advance()

    spot = POWER.quote()
    fut = ICE.quote()
    spread = fut - spot
    logger.debug("TICK spot=%s fut=%s spread=%s", spot, fut, spread)

    trade, qty, spread_signal = should_trade(spot, fut)
    METRICS.spread.set(spread_signal)
    if not trade:
        return False

    notional = qty * spot
    if notional > settings.max_notional_per_trade:
        logger.warning(
            "Notional £%.2f > cap £%s",
            notional,
            settings.max_notional_per_trade,
        )
        METRICS.trades_blocked.inc()
        return False

    if os.getenv("USE_WEB3_LOAN") == "1":
        if not settings.receiver_address:
            raise RuntimeError(
                "USE_WEB3_LOAN=1 but FLASH_LOAN_RECEIVER is not set"
            )

        loan = FlashLoanAdapter(
            lender_address=settings.flash_loan_contract,
            private_key=os.getenv("LENDER_KEY"),
            rpc_url=settings.hardhat_rpc,
        )
        receipt = loan.flash_loan(
            receiver_address=settings.receiver_address,
            amount_wei=100_000 * 10**18,
        )
        logger.info("Flash-loan transaction submitted: %s", receipt)
        return True

    with FlashLoanAdapter(limit_gbp=100_000) as wallet:
        try:
            try:
                fill_a = POWER.buy(qty, max_price=spot)
            except RuntimeError:
                return False

            save_order(
                Order(
                    id=fill_a.order_id,
                    timestamp=datetime.utcnow(),
                    symbol=settings.ice_symbol,
                    side="BUY",
                    qty_requested=qty,
                    qty_filled=fill_a.qty_mwh,
                    avg_price=fill_a.price,
                    status="PENDING",
                )
            )

            wallet["gbp"] += fill_a.qty_mwh * fill_a.price

            fill_b = ICE.sell(qty)
            wallet["gbp"] += fill_b.qty_mwh * fill_b.price

            profit = wallet["gbp"] - 100_000
            if profit >= 0:
                METRICS.profit_positive.inc(profit)
            else:
                METRICS.profit_negative.inc(-profit)
                _daily_loss += -profit
                METRICS.daily_loss.set(_daily_loss)

            save_trade(
                qty_mwh=qty,
                spot_price=spot,
                fut_price=fut,
                profit=profit,
            )

            return True
        finally:
            wallet["gbp"] = 0


def _start_api() -> None:
    import uvicorn

    try:
        uvicorn.run(
            app="app.web:api",
            host="0.0.0.0",
            port=settings.api_port,
            log_level="warning",
        )
    except OSError as exc:
        logger.warning(
            "Could not bind API port %s: %s",
            settings.api_port,
            exc,
        )


if __name__ == "__main__":
    from prometheus_client import start_http_server

    try:
        start_http_server(settings.metrics_port)
        logger.info(
            "Prometheus metrics listening on port %s",
            settings.metrics_port,
        )
    except OSError:
        logger.warning(
            "Could not bind metrics port %s; skipping",
            settings.metrics_port,
        )

    Thread(target=_start_api, daemon=True).start()
    logger.info(
        "FastAPI health + Prometheus JSON on port %s",
        settings.api_port,
    )

    logger.info("Starting flash-green PoC loop …")
    while True:
        if run_cycle():
            logger.info("✅ trade executed")
        sleep(1)
