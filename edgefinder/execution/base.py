"""Base executor interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..strategy.risk import SizedOrder


@dataclass
class ExecutionResult:
    order: SizedOrder
    success: bool
    trade_id: int = 0       # DB trade ID
    external_id: str = ""   # Platform order ID
    message: str = ""
    filled_price: float = 0.0
    filled_stake: float = 0.0


class Executor(ABC):
    mode: str  # 'paper' or 'live'

    @abstractmethod
    async def execute(self, order: SizedOrder) -> ExecutionResult:
        """Execute a single order."""

    async def execute_batch(self, orders: list[SizedOrder]) -> list[ExecutionResult]:
        """Execute a batch of orders."""
        results = []
        for order in orders:
            result = await self.execute(order)
            results.append(result)
        return results
