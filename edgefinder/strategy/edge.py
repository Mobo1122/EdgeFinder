"""Edge detection — find mispriced markets worth trading."""

import logging
from dataclasses import dataclass

from ..analysis.engine import AnalysisResult
from ..platforms.base import Market

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    market: Market
    analysis: AnalysisResult
    edge: float               # Signed: positive = market underprices, negative = overprices
    abs_edge: float           # Absolute edge size
    side: str                 # 'back' if underpriced, 'lay' if overpriced
    outcome: str              # Which outcome to bet on
    target_price: float       # Our estimated fair price
    market_price: float       # Current market price
    score: float              # Composite score for ranking


def detect_edges(
    markets: list[Market],
    analyses: list[AnalysisResult],
    min_edge: float = 0.10,
    min_confidence: float = 0.6,
    min_liquidity: float = 0,
) -> list[Opportunity]:
    """Compare AI estimates to market prices and find tradeable edges.

    Args:
        markets: List of markets with current prices
        analyses: Corresponding analysis results
        min_edge: Minimum edge (as fraction) to consider (default 10%)
        min_confidence: Minimum AI confidence to consider
        min_liquidity: Minimum market liquidity

    Returns:
        Sorted list of opportunities, best first
    """
    market_map = {m.id: m for m in markets}
    opportunities = []

    for analysis in analyses:
        market = market_map.get(analysis.market_id)
        if not market:
            continue

        if analysis.confidence < min_confidence:
            continue

        if market.liquidity < min_liquidity:
            continue

        # For binary markets: check the primary outcome
        market_price = market.outcome_prices[0] if market.outcome_prices else 0.5
        edge = analysis.estimated_probability - market_price
        abs_edge = abs(edge)

        if abs_edge < min_edge:
            continue

        # Determine trade direction
        if edge > 0:
            # Market underprices this outcome → BACK it
            side = "back"
            outcome = market.outcomes[0] if market.outcomes else "Yes"
        else:
            # Market overprices this outcome → LAY it (or back the opposite)
            side = "lay"
            outcome = market.outcomes[0] if market.outcomes else "Yes"
            # On platforms without lay, back the other side
            if len(market.outcomes) == 2:
                side = "back"
                outcome = market.outcomes[1]

        # Score: edge magnitude * confidence * log(liquidity)
        import math
        liquidity_factor = math.log10(max(market.liquidity, 1) + 1) / 5
        score = abs_edge * analysis.confidence * (0.5 + liquidity_factor)

        opportunities.append(Opportunity(
            market=market,
            analysis=analysis,
            edge=edge,
            abs_edge=abs_edge,
            side=side,
            outcome=outcome,
            target_price=analysis.estimated_probability,
            market_price=market_price,
            score=score,
        ))

    # Sort by score descending
    opportunities.sort(key=lambda o: o.score, reverse=True)

    logger.info(
        f"Found {len(opportunities)} opportunities from {len(analyses)} analyses "
        f"(min_edge={min_edge:.0%}, min_confidence={min_confidence:.0%})"
    )
    return opportunities
