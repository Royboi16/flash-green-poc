# app/orchestrator.py
"""
Drives a single arbitrage cycle and (if run as __main__)
loops forever once every second.
"""

import sqlite3
from datetime import date, datetime, time, timezone
from time import sleep

from app.config import settings
from app.logger import logger
from app.metrics import METRICS
from app.loan_repo import FnalityHQLAXFlashAdapter, RepoSettlement, RepoSettlementError
from app.storage import (
    Order,
    get_connection,
    get_open_orders,
    save_order,
    save_trade,
    update_order,
)
from app.strategy import QuoteSnapshot, TradePlan, select_route

# --- choose PowerExchange implementation ------------------------------------
if settings.use_powerledger_live:
    from app.exchange_powerledger import PowerledgerExchange as PowerExchange
elif settings.use_depth_sim:
    from app.exchange import DepthAwarePowerExchange as PowerExchange
elif settings.use_ice_live:
    from app.exchange_ice import ICEPowerExchange as PowerExchange
else:
    from app.exchange import PowerCsvExchange as PowerExchange

# instantiate power exchange
if settings.use_powerledger_live or settings.use_ice_live:
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

# futures: live adapter when enabled
if settings.use_ice_live:
    if settings.futures_live_adapter == "ice_rest":
        from app.exchange_ice import ICERepoFuturesExchange as FuturesExchange
    elif settings.futures_live_adapter == "fnality_repo":
        from app.exchange_repo import FnalityRepoExchange as FuturesExchange
    else:  # pragma: no cover - Literal guards valid inputs
        from app.exchange_ice import ICERepoFuturesExchange as FuturesExchange

    FUTURES = FuturesExchange()
else:
    from app.exchange import IceCsvExchange

    FUTURES = IceCsvExchange()

# flash-loan adapter (unchanged)
if settings.use_web3_loan:
    from app.loan_web3 import Web3FlashLoan as FlashLoanAdapter
else:
    from app.loan import flash_loan as FlashLoanAdapter


def _today() -> date:
    return date.today()


def _parse_window(raw: str) -> tuple[time, time]:
    start_s, end_s = raw.split("-")
    start_parts = [int(part) for part in start_s.split(":", maxsplit=1)]
    end_parts = [int(part) for part in end_s.split(":", maxsplit=1)]
    return time(start_parts[0], start_parts[1]), time(end_parts[0], end_parts[1])


# Globals to track daily PnL
_current_day: date = _today()
_daily_loss: float = 0.0


def _settle_open_orders(
    power_exchange: PowerExchange, conn: sqlite3.Connection
) -> None:
    for order in get_open_orders(conn=conn):
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
        update_order(order.id, filled, avg_price, status, conn=conn)


def _persist_buy_order(fill_a, qty: float) -> str:
    order_id = fill_a.order_id or f"sim-{datetime.utcnow().isoformat()}"
    with get_connection() as conn:
        save_order(
            Order(
                id=order_id,
                timestamp=datetime.utcnow(),
                symbol=settings.ice_symbol,
                side="BUY",
                qty_requested=qty,
                qty_filled=fill_a.qty_mwh,
                avg_price=fill_a.price,
                status="PENDING",
            ),
            conn=conn,
        )
    return order_id


def _record_trade(
    fill_a,
    fill_b,
    qty: float,
    spot: float,
    fut: float,
    repo_settlement: RepoSettlement | None = None,
) -> float:
    global _daily_loss

    profit = fill_a.qty_mwh * fill_a.price + fill_b.qty_mwh * fill_b.price

    if profit >= 0:
        METRICS.profit_positive.inc(profit)
    else:
        loss = -profit
        METRICS.profit_negative.inc(loss)
        _daily_loss += loss
        METRICS.daily_loss.set(_daily_loss)

    with get_connection() as conn:
        save_trade(
            qty_mwh=qty,
            spot_price=spot,
            fut_price=fut,
            profit=profit,
            repo_tx_hash=repo_settlement.tx_hash if repo_settlement else None,
            repo_cash_token=repo_settlement.cash_token if repo_settlement else None,
            repo_asset_token=repo_settlement.asset_token if repo_settlement else None,
            repo_timestamp=repo_settlement.timestamp if repo_settlement else None,
            conn=conn,
        )

    return profit


def _check_notional(fill_a) -> bool:
    trade_notional = abs(fill_a.qty_mwh * fill_a.price)
    if trade_notional > settings.max_notional_per_trade:
        logger.warning(
            "Notional £%.2f > cap £%s", trade_notional, settings.max_notional_per_trade
        )
        METRICS.trades_blocked.inc()
        return False
    return True


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

    now = datetime.now(tz=timezone.utc)
    live_trading = settings.use_powerledger_live or settings.use_ice_live
    if live_trading and not settings.allow_weekend_trading and now.weekday() >= 5:
        METRICS.trades_blocked.inc()
        logger.info("Weekend guard active; skipping trades on Saturday/Sunday")
        return False

    if live_trading:
        start, end = _parse_window(settings.trading_window_utc)
        now_time = now.time()
        if start <= end:
            in_window = start <= now_time <= end
        else:
            in_window = now_time >= start or now_time <= end
        if not in_window:
            METRICS.trades_blocked.inc()
            logger.info(
                "Outside configured trading window %s; current UTC %s",
                settings.trading_window_utc,
                now.strftime("%H:%M"),
            )
            return False

    if settings.use_ice_live or settings.use_powerledger_live:
        with get_connection() as conn:
            _settle_open_orders(POWER, conn)
            if get_open_orders(conn=conn):
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
    FUTURES.advance()

    spot = POWER.quote()
    fut = FUTURES.quote()
    logger.debug("TICK:   spot=%r, fut=%r, spread=%r", spot, fut, fut - spot)

    plan: TradePlan = select_route(
        QuoteSnapshot(
            spot_price=spot,
            futures_price=fut,
            slippage_bp=settings.slippage_bp,
        )
    )
    METRICS.spread.set(plan.spread)
    logger.debug(
        " SIGNAL: trade=%r, qty=%r, spread=%r, path=%s",
        plan.execute,
        plan.qty_mwh,
        plan.spread,
        plan.path,
    )

    logger.debug(
        "DEBUG tick: spot=%s, fut=%s, spread=%s, trade=%s, qty=%s, path=%s",
        spot,
        fut,
        plan.spread,
        plan.execute,
        plan.qty_mwh,
        plan.path,
    )

    if not plan.execute:
        if plan.block_reason:
            METRICS.trades_blocked.inc()
        return False

    qty = plan.qty_mwh

    notional = qty * spot
    if notional > settings.max_notional_per_trade:
        logger.warning(
            "Notional £%.2f > cap £%s", notional, settings.max_notional_per_trade
        )
        METRICS.trades_blocked.inc()
        return False

    if settings.use_web3_loan:
        repo_adapter = FnalityHQLAXFlashAdapter(
            flash_loan=FlashLoanAdapter(
                lender_address=settings.flash_loan_contract,
                private_key=settings.lender_private_key,
                rpc_url=str(settings.hardhat_rpc),
            ),
            receiver_address=settings.receiver_address,
            cash_token=settings.fnality_cash_token,
            asset_token=settings.hqlax_token,
        )

        try:
            with repo_adapter.transactional_repo(
                cash_amount_wei=int(settings.loan_limit_gbp * 10**18)
            ) as settlement:
                fill_a = POWER.buy(qty, max_price=spot)
                if not _check_notional(fill_a):
                    raise RepoSettlementError("Notional limit exceeded")

                _persist_buy_order(fill_a, qty)
                fill_b = FUTURES.sell(qty)
                _record_trade(fill_a, fill_b, qty, spot, fut, settlement)
                return True
        except RepoSettlementError as exc:
            METRICS.trades_blocked.inc()
            logger.warning("Flash-loan repo trade aborted: %s", exc)
            return False

    with FlashLoanAdapter(limit_gbp=settings.loan_limit_gbp) as wallet:
        try:
            try:
                fill_a = POWER.buy(qty, max_price=spot)
            except RuntimeError:
                return False

            if not _check_notional(fill_a):
                return False

            _persist_buy_order(fill_a, qty)

            wallet["gbp"] += fill_a.qty_mwh * fill_a.price

            fill_b = FUTURES.sell(qty)
            wallet["gbp"] += fill_b.qty_mwh * fill_b.price

            profit = _record_trade(fill_a, fill_b, qty, spot, fut)
            wallet["gbp"] = settings.loan_limit_gbp + profit

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
