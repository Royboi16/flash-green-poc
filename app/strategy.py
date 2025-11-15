# app/strategy.py

from app.config import settings
from app.logger import logger


def kelly_size(
    spread: float,
    stdev: float = 35,
    bank: float = 50_000,
) -> float:
    """Return a crude Kelly position size in MWh."""

    f_star = spread / (stdev**2)
    size_fraction = min(max(f_star, 0), 0.10)
    return size_fraction * bank / spread


def should_trade(spot: float, futs: float) -> tuple[bool, float, float]:
    """
    Decide whether to trade this tick.
    Returns (trade_flag, qty_mwh, spread).
    """
    spread = futs - spot

    # --- DEBUG: log inputs and thresholds ---
    logger.debug(
        "STRATEGY spot=%.2f futs=%.2f spread=%.2f neg=%s min=%s",
        spot,
        futs,
        spread,
        settings.neg_threshold,
        settings.spread_min,
    )

    # Trading condition
    if spot <= settings.neg_threshold and spread >= settings.spread_min:
        qty = kelly_size(spread)
        logger.debug("STRATEGY ⇒ trade=True qty=%.4f", qty)
        return True, qty, spread

    logger.debug("STRATEGY ⇒ trade=False")
    return False, 0.0, spread
