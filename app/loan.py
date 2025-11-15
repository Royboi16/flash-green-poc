# app/loan.py
import time
from contextlib import contextmanager
from typing import List, Optional


class RevertableLoanError(Exception):
    pass


@contextmanager
def flash_loan(
    limit_gbp: float,
    timeout_s: int = 30,
    principal_asset: str = "gbp",
    repayment_assets: Optional[List[str]] = None,
):
    """Simulate a multi-asset flash-loan ledger."""

    if repayment_assets:
        seen: List[str] = []
        for asset in repayment_assets:
            if asset not in seen:
                seen.append(asset)
        assets = seen
    else:
        assets = [principal_asset]
    if principal_asset not in assets:
        assets.insert(0, principal_asset)

    start = time.time()
    balance = {asset: 0.0 for asset in assets}
    balance[principal_asset] = limit_gbp

    yield balance            # ---------- user code runs here ----------

    elapsed = time.time() - start
    if elapsed > timeout_s:
        raise RevertableLoanError(
            f"Flash-loan window exceeded: {elapsed:.2f}s > {timeout_s}s"
        )

    offenders = [asset for asset, value in balance.items() if abs(value) > 1e-9]
    if offenders:
        raise RevertableLoanError(
            f"Flash-loan NOT repaid on assets: {', '.join(offenders)}"
        )
