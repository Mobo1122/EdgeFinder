"""Smarkets Exchange connector.

Smarkets is a UK betting exchange with lower commissions (2%) than Betfair.
Docs: https://docs.smarkets.com/

Key concepts:
- Events contain markets. Markets have contracts (outcomes).
- Prices are in percentage (0-100) representing implied probability.
- 2% commission on net winnings.
"""

import logging

import httpx

from .base import Market, Order, OrderResult, Platform

logger = logging.getLogger(__name__)

BASE_URL = "https://api.smarkets.com/v3"


class SmarketsPlatform(Platform):
    name = "smarkets"

    def __init__(self, config: dict, api_token: str = ""):
        self.config = config
        self.api_token = api_token
        self.min_volume = config.get("min_volume", 1000)
        self.client = httpx.AsyncClient(
            base_url=config.get("base_url", BASE_URL),
            timeout=30.0,
        )

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Session-Token {self.api_token}"
        return headers

    async def get_active_markets(self, limit: int = 50) -> list[Market]:
        # Fetch popular events across politics, current affairs, entertainment
        try:
            resp = await self.client.get(
                "/events/",
                params={
                    "state": "live,upcoming",
                    "type_domain": "politics,current_affairs,entertainment",
                    "type_scope": "single_event",
                    "limit": limit,
                    "sort": "-volume",
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            events_data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch Smarkets events: {e}")
            return []

        events = events_data.get("events", [])
        if not events:
            return []

        # Get markets for these events
        event_ids = [e["id"] for e in events]
        markets = []

        for event in events:
            event_markets = await self._get_event_markets(event)
            markets.extend(event_markets)
            if len(markets) >= limit:
                break

        logger.info(f"Fetched {len(markets)} Smarkets markets")
        return markets[:limit]

    async def _get_event_markets(self, event: dict) -> list[Market]:
        event_id = event["id"]
        try:
            resp = await self.client.get(
                f"/events/{event_id}/markets/",
                headers=self._headers(),
            )
            resp.raise_for_status()
            markets_data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch Smarkets markets for event {event_id}: {e}")
            return []

        results = []
        for mkt in markets_data.get("markets", []):
            market_id = mkt["id"]
            contracts = await self._get_contracts(market_id)
            if not contracts:
                continue

            outcomes = []
            outcome_prices = []
            for c in contracts:
                outcomes.append(c.get("name", "Unknown"))
                # Smarkets quotes prices as percentages
                price_pct = c.get("price", {}).get("mid", 50)
                outcome_prices.append(round(price_pct / 100.0, 4))

            results.append(Market(
                id=f"smarkets_{market_id}",
                platform="smarkets",
                question=mkt.get("name", event.get("name", "")),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                volume=mkt.get("volume", 0) or 0,
                liquidity=0,  # Smarkets doesn't expose this directly
                category=event.get("type_domain", ""),
                end_date=event.get("start_datetime", ""),
                url=f"https://smarkets.com/event/{event_id}",
                description=mkt.get("description", "")[:500],
                extra_data={
                    "event_id": event_id,
                    "market_id": market_id,
                    "contracts": [
                        {"id": c["id"], "name": c.get("name", "")}
                        for c in contracts
                    ],
                },
            ))

        return results

    async def _get_contracts(self, market_id: str) -> list[dict]:
        try:
            resp = await self.client.get(
                f"/markets/{market_id}/contracts/",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("contracts", [])
        except Exception as e:
            logger.error(f"Failed to fetch Smarkets contracts for {market_id}: {e}")
            return []

    async def get_market_details(self, market_id: str) -> Market | None:
        raw_id = market_id.replace("smarkets_", "")
        try:
            resp = await self.client.get(
                f"/markets/{raw_id}/",
                headers=self._headers(),
            )
            resp.raise_for_status()
            mkt = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch Smarkets market {market_id}: {e}")
            return None

        contracts = await self._get_contracts(raw_id)
        outcomes = []
        outcome_prices = []
        for c in contracts:
            outcomes.append(c.get("name", "Unknown"))
            price_pct = c.get("price", {}).get("mid", 50)
            outcome_prices.append(round(price_pct / 100.0, 4))

        return Market(
            id=market_id,
            platform="smarkets",
            question=mkt.get("name", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            volume=mkt.get("volume", 0) or 0,
            liquidity=0,
            category=mkt.get("type_domain", ""),
            end_date=mkt.get("start_datetime", ""),
            url=f"https://smarkets.com/market/{raw_id}",
            description=mkt.get("description", "")[:500],
            extra_data={
                "market_id": raw_id,
                "contracts": [
                    {"id": c["id"], "name": c.get("name", "")}
                    for c in contracts
                ],
            },
        )

    async def place_order(self, order: Order) -> OrderResult:
        if not self.api_token:
            return OrderResult(success=False, message="No Smarkets API token configured")

        raw_market_id = order.market_id.replace("smarkets_", "")
        side = "buy" if order.side == "back" else "sell"
        price_pct = int(order.price * 10000)  # Smarkets uses basis points

        try:
            resp = await self.client.post(
                f"/orders/",
                json={
                    "market_id": raw_market_id,
                    "contract_id": order.extra_data.get("contract_id", "") if hasattr(order, "extra_data") else "",
                    "side": side,
                    "price": price_pct,
                    "quantity": int(order.stake * 100),  # Smarkets uses pence
                    "type": "limit",
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            result = resp.json()
            return OrderResult(
                success=True,
                order_id=str(result.get("order_id", "")),
                filled_price=order.price,
                filled_stake=order.stake,
            )
        except Exception as e:
            return OrderResult(success=False, message=str(e))

    async def close(self) -> None:
        await self.client.aclose()
