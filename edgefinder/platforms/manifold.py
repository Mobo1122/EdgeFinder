"""Manifold Markets connector — free API, no auth needed for reading."""

import logging

import httpx

from .base import Market, Order, OrderResult, Platform

logger = logging.getLogger(__name__)

BASE_URL = "https://api.manifold.markets/v0"


class ManifoldPlatform(Platform):
    name = "manifold"

    def __init__(self, config: dict, api_key: str = ""):
        self.config = config
        self.api_key = api_key
        self.min_volume = config.get("min_volume", 100)
        self.client = httpx.AsyncClient(
            base_url=config.get("base_url", BASE_URL),
            timeout=30.0,
        )

    async def get_active_markets(self, limit: int = 50) -> list[Market]:
        try:
            resp = await self.client.get(
                "/markets",
                params={
                    "limit": min(limit, 100),
                    "sort": "liquidity",
                    "filter": "open",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch Manifold markets: {e}")
            return []

        markets = []
        for m in data:
            if m.get("outcomeType") != "BINARY":
                continue
            volume = m.get("volume", 0) or 0
            if volume < self.min_volume:
                continue

            prob = m.get("probability", 0.5)
            markets.append(Market(
                id=f"manifold_{m['id']}",
                platform="manifold",
                question=m.get("question", ""),
                outcomes=["Yes", "No"],
                outcome_prices=[prob, 1.0 - prob],
                volume=volume,
                liquidity=m.get("totalLiquidity", 0) or 0,
                category=m.get("groupSlugs", [""])[0] if m.get("groupSlugs") else "",
                end_date=m.get("closeTime", ""),
                url=m.get("url", ""),
                description=m.get("textDescription", "")[:500],
                extra_data={"slug": m.get("slug", "")},
            ))

        logger.info(f"Fetched {len(markets)} Manifold markets")
        return markets

    async def get_market_details(self, market_id: str) -> Market | None:
        raw_id = market_id.replace("manifold_", "")
        try:
            resp = await self.client.get(f"/market/{raw_id}")
            resp.raise_for_status()
            m = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch Manifold market {market_id}: {e}")
            return None

        prob = m.get("probability", 0.5)
        return Market(
            id=market_id,
            platform="manifold",
            question=m.get("question", ""),
            outcomes=["Yes", "No"],
            outcome_prices=[prob, 1.0 - prob],
            volume=m.get("volume", 0) or 0,
            liquidity=m.get("totalLiquidity", 0) or 0,
            category=m.get("groupSlugs", [""])[0] if m.get("groupSlugs") else "",
            end_date=m.get("closeTime", ""),
            url=m.get("url", ""),
            description=m.get("textDescription", "")[:500],
        )

    async def place_order(self, order: Order) -> OrderResult:
        if not self.api_key:
            return OrderResult(success=False, message="No Manifold API key configured")

        outcome = "YES" if order.outcome.lower() in ("yes", "back") else "NO"
        try:
            resp = await self.client.post(
                "/bet",
                json={
                    "contractId": order.market_id.replace("manifold_", ""),
                    "amount": int(order.stake),
                    "outcome": outcome,
                },
                headers={"Authorization": f"Key {self.api_key}"},
            )
            resp.raise_for_status()
            result = resp.json()
            return OrderResult(
                success=True,
                order_id=str(result.get("betId", "")),
                filled_price=result.get("probAfter", order.price),
                filled_stake=order.stake,
            )
        except Exception as e:
            return OrderResult(success=False, message=str(e))

    async def close(self) -> None:
        await self.client.aclose()
