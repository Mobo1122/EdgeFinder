"""Risk management — position sizing and exposure limits."""

import logging
from dataclasses import dataclass

from ..db.database import db_session, get_open_trades
from .edge import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class SizedOrder:
    opportunity: Opportunity
    stake: float        # Amount to bet in £
    expected_value: float  # Expected profit


def kelly_fraction(edge: float, odds: float) -> float:
    """Calculate Kelly criterion bet fraction.

    For a bet with probability p of winning at decimal odds b:
    f* = (bp - q) / b
    where q = 1 - p, and b = decimal_odds - 1 (net odds)

    Args:
        edge: Our estimated edge (estimated_prob - market_prob)
        odds: Decimal odds of the bet

    Returns:
        Optimal fraction of bankroll to bet (can be negative = don't bet)
    """
    if odds <= 1:
        return 0

    # Convert to our framework
    # If market price is p_market, decimal odds = 1/p_market
    # Our estimated probability is p_market + edge
    p_market = 1.0 / odds if odds > 0 else 0.5
    p_est = p_market + edge
    p_est = max(0.01, min(0.99, p_est))  # Clamp

    b = odds - 1  # Net odds
    q = 1 - p_est

    f = (b * p_est - q) / b
    return max(0, f)


def size_positions(
    opportunities: list[Opportunity],
    config: dict,
) -> list[SizedOrder]:
    """Size positions using fractional Kelly criterion with exposure limits.

    Args:
        opportunities: Ranked list of trading opportunities
        config: Risk configuration dict with keys:
            - kelly_fraction: Fraction of full Kelly to use (default 0.25)
            - max_position_size: Max stake per market
            - max_portfolio_exposure: Max total exposure
            - max_correlated_exposure: Max exposure on related markets

    Returns:
        List of sized orders ready for execution
    """
    kelly_frac = config.get("kelly_fraction", 0.25)
    max_position = config.get("max_position_size", 50.0)
    max_portfolio = config.get("max_portfolio_exposure", 500.0)

    # Get current exposure
    with db_session() as conn:
        open_trades = get_open_trades(conn)
    current_exposure = sum(t["stake"] for t in open_trades)
    remaining_budget = max_portfolio - current_exposure

    if remaining_budget <= 0:
        logger.warning(
            f"Portfolio exposure limit reached (£{current_exposure:.2f}/£{max_portfolio:.2f})"
        )
        return []

    # Check if we already have positions in any of these markets
    existing_market_ids = {t["market_id"] for t in open_trades}

    orders = []
    for opp in opportunities:
        if remaining_budget <= 0:
            break

        # Skip if we already have a position in this market
        if opp.market.id in existing_market_ids:
            logger.debug(f"Skipping {opp.market.id} — already have position")
            continue

        # Calculate Kelly stake
        market_price = opp.market_price
        if market_price <= 0 or market_price >= 1:
            continue

        decimal_odds = 1.0 / market_price
        full_kelly = kelly_fraction(opp.edge, decimal_odds)

        if full_kelly <= 0:
            continue

        # Apply fractional Kelly
        stake = full_kelly * kelly_frac * max_portfolio
        # Clamp to limits
        stake = min(stake, max_position, remaining_budget)
        stake = round(stake, 2)

        if stake < 1.0:  # Minimum £1 bet
            continue

        # Expected value
        ev = stake * opp.abs_edge

        orders.append(SizedOrder(
            opportunity=opp,
            stake=stake,
            expected_value=ev,
        ))

        remaining_budget -= stake
        existing_market_ids.add(opp.market.id)

    logger.info(
        f"Sized {len(orders)} orders from {len(opportunities)} opportunities "
        f"(total stake: £{sum(o.stake for o in orders):.2f})"
    )
    return orders
