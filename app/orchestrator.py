# app/orchestrator.py
from app.exchange import MockPowerLedger, MockICE
from app.loan import flash_loan
from app.strategy import should_trade
from app.metrics import METRICS

pl  = MockPowerLedger()
ice = MockICE()

def run_cycle():
    spot = pl.quote()
    fut  = ice.quote()
    trade, qty, spread = should_trade(spot, fut)

    if not trade:
        return False

    with flash_loan(limit_gbp=100_000):              # ---- loan opens ----
        # Leg A – buy negative‑price power
        fill_a = pl.buy(qty, max_price=0)
        cost   = fill_a.qty_mwh * fill_a.price

        # Leg B – short Baseload future
        fill_b = ice.sell(qty)
        cash_in = fill_b.qty_mwh * fill_b.price

        profit = cash_in + cost                    # cost is negative 👍
        METRICS.profit.inc(profit)
        # loan balance net‑zeros on exit           # ---- auto‑repay ----

    return True

