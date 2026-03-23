"""Portfolio tracking — monitor positions and check for resolved markets."""

import logging

from ..db.database import (
    close_trade,
    db_session,
    get_open_trades,
    snapshot_portfolio,
)
from ..platforms.base import Platform

logger = logging.getLogger(__name__)


async def check_resolutions(platforms: dict[str, Platform]) -> int:
    """Check if any open positions have resolved and close them.

    Returns:
        Number of trades closed
    """
    closed_count = 0

    with db_session() as conn:
        open_trades = get_open_trades(conn)

        for trade in open_trades:
            platform = platforms.get(trade["platform"])
            if not platform:
                continue

            market = await platform.get_market_details(trade["market_id"])
            if not market:
                continue

            # Check if market has extra_data indicating resolution
            extra = market.extra_data or {}
            resolved = extra.get("resolved", False)

            if not resolved:
                continue

            resolution = extra.get("resolution_outcome", "")
            pnl = _calculate_pnl(trade, resolution)

            close_trade(conn, trade["id"], pnl)
            closed_count += 1
            logger.info(
                f"Closed trade {trade['id']} on {trade['market_id']} — "
                f"P&L: £{pnl:+.2f}"
            )

        # Take a portfolio snapshot
        snapshot_portfolio(conn)

    if closed_count > 0:
        logger.info(f"Resolved {closed_count} trades")
    return closed_count


def _calculate_pnl(trade: dict, resolution: str) -> float:
    """Calculate profit/loss for a resolved trade.

    For a back bet:
        Win: stake * (1/price - 1)  [profit at decimal odds]
        Lose: -stake

    For a lay bet:
        Win (outcome doesn't happen): stake * price / (1 - price)
        Lose (outcome happens): -stake * (1/price - 1)
    """
    stake = trade["stake"]
    price = trade["price"]  # Probability we bought at
    outcome = trade["outcome"]
    side = trade["side"]

    # Did our chosen outcome win?
    won = resolution.lower() == outcome.lower()

    if side == "back":
        if won:
            decimal_odds = 1.0 / price if price > 0 else 1
            return stake * (decimal_odds - 1)
        else:
            return -stake
    else:  # lay
        if won:  # Bad for us — the outcome we laid against happened
            decimal_odds = 1.0 / price if price > 0 else 1
            return -stake * (decimal_odds - 1)
        else:  # Good — outcome didn't happen
            return stake * price / (1 - price) if price < 1 else stake

