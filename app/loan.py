# app/loan.py
import time
from contextlib import contextmanager

class RevertableLoanError(Exception):
    pass


@contextmanager
def flash_loan(limit_gbp: float, timeout_s: int = 30):
    """
    Pretend we just borrowed `limit_gbp` with zero collateral.
    If the caller fails to repay by exiting the context, we raise.
    """
    start = time.time()
    balance = {"gbp": limit_gbp}

    yield balance            # ---------- user code runs here ----------

    delta = balance["gbp"]         # should be back at 0
    if delta != 0 or time.time() - start > timeout_s:
        raise RevertableLoanError(
            f"Flash-loan NOT repaid: {delta:+.2f} GBP after {timeout_s}s"
        )

