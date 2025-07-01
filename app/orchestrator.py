# app/orchestrator.py
"""
Drives a single arbitrage cycle and (if run as __main__)
loops forever once every second.
"""

from time import sleep
from app import logger                      # Rich logger
from app.metrics import METRICS
from app.exchange import PowerCsvExchange, DepthAwarePowerExchange, LivePowerExchange, IceCsvExchange
from app.strategy import should_trade
from app.storage import save_trade
from app.config import settings
import os
from datetime import datetime, date

# ── Allow test-friendly override of “today” ────────────────────────────────
def _today() -> date:
    return date.today()

# Globals to track daily PnL
_current_day: date = _today()
_daily_loss:   float = 0.0

if os.getenv("USE_WEB3_LOAN") == "1":
    from app.loan_web3 import Web3FlashLoan as FlashLoanAdapter
else:
    from app.loan import flash_loan as FlashLoanAdapter

print(settings.flash_loan_contract)  # → "0xYourDeployedContractAddress"

if settings.use_live_feed:
    pl = LivePowerExchange(
        settings.live_exchange,
        settings.live_symbol,
        settings.live_api_key,
        settings.live_api_secret,
    )
elif settings.use_depth_sim:
    pl = DepthAwarePowerExchange(
        settings.exec_latency_ms,
        settings.slippage_bp,
        settings.book_levels,
        settings.book_size_mwh,
    )
else:
    pl = PowerCsvExchange()
    
ice = IceCsvExchange()


def run_cycle() -> bool:
    global _current_day, _daily_loss
    
    # reset daily loss at UTC midnight
    today = _today()
    if today != _current_day:
        _current_day = today
        _daily_loss   = 0.0
        METRICS.daily_loss.set(_daily_loss)
    
    # master switch
    if not settings.trading_enabled:
        METRICS.trades_blocked.inc()
        return False
    
    # advance both feeds each tick
    now = datetime.utcnow()
    pl.advance(); ice.advance()

    spot = pl.quote()
    fut  = ice.quote()

    trade, qty, spread = should_trade(spot, fut)
    METRICS.spread.set(spread)

    if not trade:
        return False
        
    # notional check (qty×spot gives £ exposure)
    notional = qty * spot
    if notional > settings.max_notional_per_trade:
        logger.warning(f"Notional £{notional:.2f} > cap £{settings.max_notional_per_trade}")
        METRICS.trades_blocked.inc()
        return False

    # ── On‐chain flash‐loan branch ─────────────────────────────────────────────
    if os.getenv("USE_WEB3_LOAN") == "1":
        if not settings.receiver_address:
            raise RuntimeError(
                "USE_WEB3_LOAN=1 but FLASH_LOAN_RECEIVER is not set in the environment"
            )

        loan = FlashLoanAdapter(
            lender_address=settings.flash_loan_contract,
            private_key=os.getenv("LENDER_KEY"),
        )
        receipt = loan.flash_loan(
            receiver_address=settings.receiver_address,
            amount_wei=100_000 * 10**18,
        )
        # You could inspect receipt.status here; assume success if no exception
        return True

    # ── Mock flash‐loan branch ─────────────────────────────────────────────────
    else:
        with FlashLoanAdapter(limit_gbp=100_000) as wallet:
            try:
                # Leg A – buy power (strict ≤ £0/MWh)
                try:
                    fill_a = pl.buy(qty, max_price=0)
                except RuntimeError:
                    # Slipped above £0; skip this tick
                    return False

                # Only reached if buy succeeded
                wallet["gbp"] += fill_a.qty_mwh * fill_a.price

                # Leg B – short Baseload future
                fill_b = ice.sell(qty)
                wallet["gbp"] += fill_b.qty_mwh * fill_b.price

                # Record PnL
                profit = wallet["gbp"] - 100_000
                if profit >= 0:
                    METRICS.profit_positive.inc(profit)
                else:
                    METRICS.profit_negative.inc(-profit)

                # track daily loss
                if profit < 0:
                    _daily_loss += -profit
                    METRICS.daily_loss.set(_daily_loss)

                save_trade(
                    qty_mwh=qty,
                    spot_price=spot,
                    fut_price=fut,
                    profit=profit
                )

                return True

            finally:
                # ALWAYS repay principal before context exits
                wallet["gbp"] = 0
    # ------------- flash‑loan auto‑closes -------------


# ---------------------------------------------------------------------------
# Simple CLI loop
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # ─── imports ──────────────────────────────────────────────────────────
    from prometheus_client import start_http_server
    from app.config        import settings
    from app               import logger
    import uvicorn
    from threading import Thread
    from time      import sleep

    # ─── start Prometheus exporter ────────────────────────────────────────
    try:
        start_http_server(settings.metrics_port)
        logger.info(f"Prometheus metrics listening on {settings.metrics_port}")
    except OSError:
        logger.warning(
            f"Could not bind metrics port {settings.metrics_port}; skipping"
        )

    # ─── helper to start FastAPI in a thread ─────────────────────────────
    def _start_api():
        try:
            uvicorn.run(
                app="app.web:api",
                host="0.0.0.0",
                port=settings.api_port,
                log_level="warning",
            )
        except OSError as e:
            logger.warning(
                f"Could not bind API port {settings.api_port}: {e}"
            )

    # ─── launch FastAPI ───────────────────────────────────────────────────
    Thread(target=_start_api, daemon=True).start()
    logger.info(f"FastAPI health & Prom JSON on port {settings.api_port}")

    # ─── main loop ────────────────────────────────────────────────────────
    logger.info("Starting flash-green PoC loop …")
    while True:
        if run_cycle():
            logger.info("[green]✅  trade executed[/green]")
        sleep(1)