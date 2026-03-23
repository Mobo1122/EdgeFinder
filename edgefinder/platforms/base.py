"""Abstract base class for platform connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Market:
    id: str
    platform: str
    question: str
    outcomes: list[str]           # e.g. ["Yes", "No"] or ["Team A", "Team B", "Draw"]
    outcome_prices: list[float]   # probability for each outcome (0-1)
    volume: float = 0.0
    liquidity: float = 0.0
    category: str = ""
    end_date: str = ""
    url: str = ""
    description: str = ""
    extra_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "question": self.question,
            "category": self.category,
            "current_price": self.outcome_prices[0] if self.outcome_prices else None,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "end_date": self.end_date,
            "url": self.url,
            "extra_data": {
                "outcomes": self.outcomes,
                "outcome_prices": self.outcome_prices,
                "description": self.description,
            },
        }


@dataclass
class Order:
    market_id: str
    platform: str
    side: str          # 'back' or 'lay'
    outcome: str       # which outcome to bet on
    price: float       # odds (decimal) or probability depending on platform
    stake: float       # amount in £


@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    message: str = ""
    filled_price: float = 0.0
    filled_stake: float = 0.0


class Platform(ABC):
    """Base class all platform connectors must implement."""

    name: str

    @abstractmethod
    async def get_active_markets(self, limit: int = 50) -> list[Market]:
        """Fetch currently active markets from the platform."""

    @abstractmethod
    async def get_market_details(self, market_id: str) -> Market | None:
        """Get detailed info for a specific market."""

    async def place_order(self, order: Order) -> OrderResult:
        """Place an order. Override for live trading support."""
        return OrderResult(success=False, message="Live trading not implemented")

    async def close(self) -> None:
        """Clean up resources (HTTP clients etc)."""
