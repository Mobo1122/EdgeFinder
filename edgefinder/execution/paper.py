"""Paper trading executor — simulates trades without real money."""

import logging
import random

from ..db.database import db_session, insert_trade
from ..strategy.risk import SizedOrder
from .base import ExecutionResult, Executor

logger = logging.getLogger(__name__)


class PaperExecutor(Executor):
    mode = "paper"

    def __init__(self, slippage: float = 0.01):
        """
        Args:
            slippage: Simulated slippage as fraction (default 1%)
        """
        self.slippage = slippage

    async def execute(self, order: SizedOrder) -> ExecutionResult:
        """Simulate a trade at market price + simulated slippage."""
        opp = order.opportunity

        # Simulate slippage — price moves against us slightly
        slip = random.uniform(0, self.slippage)
        if opp.side == "back":
            # Buying: price goes up slightly (worse for us)
            filled_price = opp.market_price * (1 + slip)
        else:
            # Selling/laying: price goes down slightly (worse for us)
            filled_price = opp.market_price * (1 - slip)

        filled_price = round(max(0.01, min(0.99, filled_price)), 4)

        # Record in database
        trade_data = {
            "market_id": opp.market.id,
            "platform": opp.market.platform,
            "side": opp.side,
            "outcome": opp.outcome,
            "price": filled_price,
            "stake": order.stake,
            "mode": "paper",
        }

        try:
            with db_session() as conn:
                trade_id = insert_trade(conn, trade_data)

            logger.info(
                f"[PAPER] {opp.side.upper()} £{order.stake:.2f} on "
                f"'{opp.outcome}' @ {filled_price:.1%} | "
                f"Edge: {opp.abs_edge:.1%} | {opp.market.question[:50]}"
            )

            return ExecutionResult(
                order=order,
                success=True,
                trade_id=trade_id,
                filled_price=filled_price,
                filled_stake=order.stake,
                message="Paper trade executed",
            )
        except Exception as e:
            logger.error(f"Failed to record paper trade: {e}")
            return ExecutionResult(
                order=order,
                success=False,
                message=str(e),
            )
