"""AI analysis engine — uses Claude to estimate true probabilities."""

import json
import logging
from dataclasses import dataclass

import anthropic

from ..platforms.base import Market
from .news import fetch_news_context
from .prompts import ANALYSIS_PROMPT, MULTI_OUTCOME_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    market_id: str
    estimated_probability: float  # For the primary outcome
    confidence: float
    edge: float                   # estimated_prob - market_price
    reasoning: str
    news_context: str
    key_factors: list[str]
    bias_detected: str = ""
    model: str = ""
    # For multi-outcome markets
    all_probabilities: dict[str, float] | None = None


class AnalysisEngine:
    def __init__(self, config: dict):
        self.model = config.get("model", "claude-sonnet-4-6")
        self.min_confidence = config.get("min_confidence", 0.6)
        self.temperature = config.get("temperature", 0.3)
        self.client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

    async def analyze_market(self, market: Market) -> AnalysisResult | None:
        """Analyze a single market and return probability estimate."""
        try:
            # Fetch news/context
            news_context = await fetch_news_context(
                market.question, market.description
            )

            # Choose prompt based on number of outcomes
            is_binary = len(market.outcomes) <= 2
            if is_binary:
                result = await self._analyze_binary(market, news_context)
            else:
                result = await self._analyze_multi(market, news_context)

            if result and result.confidence >= self.min_confidence:
                return result
            elif result:
                logger.info(
                    f"Low confidence ({result.confidence:.2f}) for: {market.question[:60]}"
                )
                return result  # Still return it, let strategy layer decide
            return None

        except Exception as e:
            logger.error(f"Analysis failed for {market.id}: {e}")
            return None

    async def _analyze_binary(
        self, market: Market, news_context: str
    ) -> AnalysisResult | None:
        prices_str = ", ".join(
            f"{o}: {p:.1%}" for o, p in zip(market.outcomes, market.outcome_prices)
        )
        prompt = ANALYSIS_PROMPT.format(
            question=market.question,
            platform=market.platform,
            outcomes=", ".join(market.outcomes),
            prices=prices_str,
            volume=market.volume,
            end_date=market.end_date or "Not specified",
            description=market.description or "None provided",
            news_context=news_context,
        )

        response = self._call_claude(prompt)
        if not response:
            return None

        try:
            data = json.loads(response)
            est_prob = float(data["probability"])
            market_price = market.outcome_prices[0] if market.outcome_prices else 0.5
            edge = est_prob - market_price

            return AnalysisResult(
                market_id=market.id,
                estimated_probability=est_prob,
                confidence=float(data.get("confidence", 0.5)),
                edge=edge,
                reasoning=data.get("reasoning", ""),
                news_context=news_context[:1000],
                key_factors=data.get("key_factors", []),
                bias_detected=data.get("bias_detected", ""),
                model=self.model,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse Claude response: {e}")
            return None

    async def _analyze_multi(
        self, market: Market, news_context: str
    ) -> AnalysisResult | None:
        outcome_list = "\n".join(
            f"  - {o}: {p:.1%}"
            for o, p in zip(market.outcomes, market.outcome_prices)
        )
        prompt = MULTI_OUTCOME_PROMPT.format(
            question=market.question,
            platform=market.platform,
            outcome_list=outcome_list,
            volume=market.volume,
            end_date=market.end_date or "Not specified",
            description=market.description or "None provided",
            news_context=news_context,
        )

        response = self._call_claude(prompt)
        if not response:
            return None

        try:
            data = json.loads(response)
            probs = data["probabilities"]
            # Find the outcome with the biggest edge
            max_edge = 0
            best_outcome_idx = 0
            for i, outcome in enumerate(market.outcomes):
                est = probs.get(outcome, market.outcome_prices[i])
                edge = abs(est - market.outcome_prices[i])
                if edge > abs(max_edge):
                    max_edge = est - market.outcome_prices[i]
                    best_outcome_idx = i

            primary_prob = probs.get(
                market.outcomes[best_outcome_idx],
                market.outcome_prices[best_outcome_idx],
            )

            return AnalysisResult(
                market_id=market.id,
                estimated_probability=primary_prob,
                confidence=float(data.get("confidence", 0.5)),
                edge=max_edge,
                reasoning=data.get("reasoning", ""),
                news_context=news_context[:1000],
                key_factors=data.get("key_factors", []),
                bias_detected=data.get("biggest_mispricing", ""),
                model=self.model,
                all_probabilities=probs,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse multi-outcome response: {e}")
            return None

    def _call_claude(self, prompt: str) -> str | None:
        """Synchronous Claude API call (anthropic SDK is sync by default)."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return None

    async def analyze_markets(
        self, markets: list[Market]
    ) -> list[AnalysisResult]:
        """Analyze a batch of markets. Returns results for all analyzable markets."""
        results = []
        for market in markets:
            result = await self.analyze_market(market)
            if result:
                results.append(result)
        logger.info(
            f"Analyzed {len(markets)} markets, got {len(results)} results"
        )
        return results
