# app/strategy.py
import numpy as np

NEG_THRESHOLD = 0          # buy power if ≤ £0/MWh
SPREAD_MIN    = 50         # execute only if gross ≥ £50

def kelly_size(spread, stdev=35, bank=50_000):
    """
    Very crude:   f* = spread / stdev² , capped at 10 % of bank.
    Each £/MWh of spread ~1 'unit'.
    """
    f_star = spread / (stdev ** 2)
    return min(max(f_star, 0), 0.10) * bank / spread   # units = MWh


def should_trade(spot, futs):
    spread = futs - spot
    if spot <= NEG_THRESHOLD and spread >= SPREAD_MIN:
        qty = kelly_size(spread)
        return True, qty, spread
    return False, 0, spread

