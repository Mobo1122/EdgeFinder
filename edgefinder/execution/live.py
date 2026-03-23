"""Live trading executor — places real orders on exchanges."""

import logging

from ..db.database import db_session, insert_trade
from ..platforms.base import Order, Platform
from ..strategy.risk import SizedOrder
from .base import ExecutionResult, Executor

logger = logging.getLogger(__name__)


class LiveExecutor(Executor):
    mode = "live"

    def __init__(self, platforms: dict[str, Platform]):
        self.platforms = platforms

    async def execute(self, order: SizedOrder) -> ExecutionResult:
        """Place a real order on the exchange."""
        opp = order.opportunity
        platform = self.platforms.get(opp.market.platform)

        if not platform:
            return ExecutionResult(
                order=order,
                success=False,
                message=f"Platform '{opp.market.platform}' not available",
            )

        # Create platform order
        platform_order = Order(
            market_id=opp.market.id,
            platform=opp.market.platform,
            side=opp.side,
            outcome=opp.outcome,
            price=opp.market_price,
            stake=order.stake,
        )

        # Execute on platform
        result = await platform.place_order(platform_order)

        # Record in database regardless of success
        trade_data = {
            "market_id": opp.market.id,
            "platform": opp.market.platform,
            "side": opp.side,
            "outcome": opp.outcome,
            "price": result.filled_price if result.success else opp.market_price,
            "stake": result.filled_stake if result.success else order.stake,
            "mode": "live",
            "external_id": result.order_id,
        }

        try:
            with db_session() as conn:
                trade_id = insert_trade(conn, trade_data)
        except Exception as e:
            logger.error(f"Failed to record live trade in DB: {e}")
            trade_id = 0

        if result.success:
            logger.info(
                f"[LIVE] {opp.side.upper()} £{result.filled_stake:.2f} on "
                f"'{opp.outcome}' @ {result.filled_price:.1%} | "
                f"Edge: {opp.abs_edge:.1%} | {opp.market.question[:50]}"
            )
        else:
            logger.warning(
                f"[LIVE] FAILED: {result.message} | {opp.market.question[:50]}"
            )

        return ExecutionResult(
            order=order,
            success=result.success,
            trade_id=trade_id,
            external_id=result.order_id,
            filled_price=result.filled_price,
            filled_stake=result.filled_stake,
            message=result.message,
        )
