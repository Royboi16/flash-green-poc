from abc import ABC, abstractmethod
from datetime import datetime


class MarketAdapter(ABC):
    """Abstract interface for spot/futures price sources."""

    @abstractmethod
    def quote(self) -> float:
        """Return the latest price."""

    @abstractmethod
    def advance(self, now: datetime) -> None:
        """Step the cursor forward in time."""

    # optional for mocks
    def buy(self, *_, **__):  # pragma: no cover - default stub
        raise NotImplementedError

    def sell(self, *_, **__):  # pragma: no cover - default stub
        raise NotImplementedError
