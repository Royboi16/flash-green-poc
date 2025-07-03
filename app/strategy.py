# app/strategy.py

from app.config import settings
from app.logger import logger


def kelly_size(spread: float, stdev: float = 35, bank: float = 50_000) -> float:
    """
    Very crude Kelly sizing: f* = spread / stdev², capped at 10% of bank.
    Returns MWh to trade.
    """
    f_star = spread / (stdev ** 2)
    return min(max(f_star, 0), 0.10) * bank / spread   # units = MWh


def should_trade(spot: float, futs: float) -> tuple[bool, float, float]:
    """
    Decide whether to trade this tick.
    Returns (trade_flag, qty_mwh, spread).
    """
    spread = futs - spot

    # --- DEBUG: log inputs and thresholds ---
    logger.debug(
        f"STRATEGY: spot={spot:.2f}, futs={futs:.2f}, spread={spread:.2f}, "
        f"neg_threshold={settings.neg_threshold}, spread_min={settings.spread_min}"
    )

    # Trading condition
    if spot <= settings.neg_threshold and spread >= settings.spread_min:
        qty = kelly_size(spread)
        logger.debug(f"STRATEGY: ⇒ trade=True, qty={qty:.4f}")
        return True, qty, spread

    logger.debug("STRATEGY: ⇒ trade=False")
    return False, 0.0, spread
