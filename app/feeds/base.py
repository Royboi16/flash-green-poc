from abc import ABC, abstractmethod
from datetime import datetime

class MarketAdapter(ABC):
    """Abstract interface for spot/futures price sources."""

    @abstractmethod
    def quote(self) -> float:                      # latest price
        ...

    @abstractmethod
    def advance(self, now: datetime) -> None:      # step the cursor
        ...

    # optional for mocks
    def buy(self, *_, **__): raise NotImplementedError
    def sell(self, *_, **__): raise NotImplementedError

