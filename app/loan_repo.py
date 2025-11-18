# app/loan_repo.py
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.logger import logger
from app.metrics import METRICS


class FlashLoanClient(Protocol):
    def flash_loan(self, receiver_address: str, amount_wei: int):  # pragma: no cover - runtime dependency
        ...


class RepoSettlementError(Exception):
    """Raised when the Fnality/HQLAˣ repo leg fails to clear atomically."""


@dataclass
class RepoSettlement:
    tx_hash: str
    cash_token: str
    asset_token: str
    timestamp: str


class FnalityHQLAXFlashAdapter:
    """Drive an atomic Fnality/HQLAˣ intraday repo via a flash-loan style flow."""

    def __init__(
        self,
        flash_loan: FlashLoanClient,
        receiver_address: str,
        cash_token: str,
        asset_token: str,
    ):
        self.flash_loan = flash_loan
        self.receiver_address = receiver_address
        self.cash_token = cash_token
        self.asset_token = asset_token

    @contextmanager
    def transactional_repo(self, cash_amount_wei: int):
        """
        Trigger a single transaction that moves cash tokens and tokenised collateral.

        The underlying flash-loan contract funds the repo, the HQLAˣ token transfer
        settles in the same transaction, and any downstream exception will be treated
        as a rollback signal so the caller can abandon the power/futures legs.
        """

        METRICS.flash_repo_attempts.inc()
        settlement: RepoSettlement | None = None
        try:
            logger.info(
                "Submitting Fnality/HQLAˣ atomic repo: cash=%s wei, asset=%s",
                cash_amount_wei,
                self.asset_token,
            )
            receipt = self.flash_loan.flash_loan(
                receiver_address=self.receiver_address,
                amount_wei=cash_amount_wei,
            )
            if getattr(receipt, "status", 0) != 1:
                raise RepoSettlementError("Fnality/HQLAˣ repo leg reverted on-chain")

            settlement = RepoSettlement(
                tx_hash=receipt.transactionHash.hex(),
                cash_token=self.cash_token,
                asset_token=self.asset_token,
                timestamp=datetime.utcnow().isoformat(),
            )
            logger.info(
                "Fnality/HQLAˣ repo pre-commit succeeded: tx=%s", settlement.tx_hash
            )
            yield settlement
        except Exception as exc:  # noqa: BLE001
            METRICS.flash_repo_failures.inc()
            METRICS.flash_repo_rollbacks.inc()
            logger.exception("Fnality/HQLAˣ repo leg failed; rolling back: %s", exc)
            raise RepoSettlementError("Fnality/HQLAˣ repo flow failed") from exc
        else:
            METRICS.flash_repo_commits.inc()
            logger.info(
                "Fnality/HQLAˣ repo committed atomically: tx=%s", settlement.tx_hash
            )
