# app/orchestrator.py
"""
Drives a single arbitrage cycle and (if run as __main__)
loops forever once every second.
"""

from datetime import date, datetime
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

# --- choose PowerExchange implementation ------------------------------------
if settings.use_ice_live:
    from app.exchange_ice import ICEPowerExchange as PowerExchange
elif settings.use_depth_sim:
    from app.exchange import DepthAwarePowerExchange as PowerExchange
else:
    from app.exchange import PowerCsvExchange as PowerExchange

# instantiate power exchange
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

# futures always CSV for now
from app.exchange import IceCsvExchange

ice = IceCsvExchange()

# flash-loan adapter (unchanged)
if settings.use_web3_loan:
    from app.loan_web3 import Web3FlashLoan as FlashLoanAdapter
else:
    from app.loan import flash_loan as FlashLoanAdapter


def _today() -> date:
    return date.today()


# Globals to track daily PnL
_current_day: date = _today()
_daily_loss: float = 0.0


def _settle_open_orders(power_exchange: PowerExchange) -> None:
    for order in get_open_orders():
        data = power_exchange._fetch_order(order.id)
        status = data["status"]
        filled = float(data.get("filled_qty", 0))
        avg_price = float(data.get("avg_price", 0))
        logger.debug(
            "Settling order %s: status=%s, filled=%s, avg_price=%s",
            order.id,
            status,
            filled,
            avg_price,
        )
        update_order(order.id, filled, avg_price, status)


def run_cycle() -> bool:
    global _current_day, _daily_loss

    logger.debug(
        "CONFIG: neg_threshold=%r, spread_min=%r, max_notional_per_trade=%r",
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
        _settle_open_orders(POWER)
        if get_open_orders():
            logger.info("Open orders pending, skipping this tick")
            return False

    if not settings.trading_enabled:
        METRICS.trades_blocked.inc()
        return False

    if _daily_loss >= settings.max_daily_loss_gbp:
        METRICS.trades_blocked.inc()
        logger.warning(
            "Daily loss cap reached (£%.2f/£%.2f); skipping trades",
            _daily_loss,
            settings.max_daily_loss_gbp,
        )
        return False

    POWER.advance()
    ice.advance()

    spot = POWER.quote()
    fut = ice.quote()
    logger.debug("TICK:   spot=%r, fut=%r, spread=%r", spot, fut, fut - spot)

    trade, qty, spread = should_trade(spot, fut)
    METRICS.spread.set(spread)
    logger.debug(" SIGNAL: trade=%r, qty=%r, spread=%r", trade, qty, spread)

    logger.debug(
        "DEBUG tick: spot=%s, fut=%s, spread=%s, trade=%s, qty=%s",
        spot,
        fut,
        spread,
        trade,
        qty,
    )

    if not trade:
        return False

    notional = qty * spot
    if notional > settings.max_notional_per_trade:
        logger.warning(
            "Notional £%.2f > cap £%s", notional, settings.max_notional_per_trade
        )
        METRICS.trades_blocked.inc()
        return False

    if settings.use_web3_loan:
        loan = FlashLoanAdapter(
            lender_address=settings.flash_loan_contract,
            private_key=settings.lender_private_key,
            rpc_url=str(settings.hardhat_rpc),
        )
        loan.flash_loan(
            receiver_address=settings.receiver_address,
            amount_wei=100_000 * 10**18,
        )
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

            fill_b = ice.sell(qty)
            wallet["gbp"] += fill_b.qty_mwh * fill_b.price

            profit = wallet["gbp"] - 100_000
            if profit >= 0:
                METRICS.profit_positive.inc(profit)
            else:
                METRICS.profit_negative.inc(-profit)

            if profit < 0:
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


if __name__ == "__main__":
    from threading import Thread

    import uvicorn
    from prometheus_client import start_http_server

    try:
        start_http_server(settings.metrics_port)
        logger.info("Prometheus metrics listening on %s", settings.metrics_port)
    except OSError:
        logger.warning(
            "Could not bind metrics port %s; skipping", settings.metrics_port
        )

    def _start_api():
        try:
            uvicorn.run(
                app="app.web:api",
                host="0.0.0.0",
                port=settings.api_port,
                log_level="warning",
            )
        except OSError as exc:
            logger.warning("Could not bind API port %s: %s", settings.api_port, exc)

    Thread(target=_start_api, daemon=True).start()
    logger.info("FastAPI health & Prom JSON on port %s", settings.api_port)

    logger.info("Starting flash-green PoC loop …")
    while True:
        if run_cycle():
            logger.info("[green]✅  trade executed[/green]")
        sleep(1)
