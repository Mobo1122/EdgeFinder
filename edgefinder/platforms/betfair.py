"""Betfair Exchange connector.

Betfair uses a certificate-based login and requires an Application Key.
Docs: https://docs.developer.betfair.com/display/1smk3cen4v3lu3yomq5qye0ni

Key concepts:
- Markets have runners (outcomes). Each runner has back/lay prices.
- Back = bet FOR an outcome. Lay = bet AGAINST.
- Prices are decimal odds (e.g., 2.0 = implied 50% probability).
- Probability = 1 / decimal_odds
"""

import logging
from pathlib import Path

import httpx

from .base import Market, Order, OrderResult, Platform

logger = logging.getLogger(__name__)

BETTING_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
LOGIN_URL = "https://identitysso-cert.betfair.com/api/certlogin"


class BetfairPlatform(Platform):
    name = "betfair"

    def __init__(
        self,
        config: dict,
        app_key: str = "",
        username: str = "",
        password: str = "",
        cert_path: str = "",
        key_path: str = "",
    ):
        self.config = config
        self.app_key = app_key
        self.username = username
        self.password = password
        self.cert_path = cert_path
        self.key_path = key_path
        self.session_token: str = ""
        self.min_volume = config.get("min_volume", 10000)
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _login(self) -> bool:
        """Authenticate with Betfair certificate login."""
        if not all([self.app_key, self.username, self.password, self.cert_path]):
            logger.warning("Betfair credentials not configured — running in read-only mode")
            return False

        cert = (self.cert_path, self.key_path) if self.key_path else self.cert_path
        try:
            resp = await self.client.post(
                LOGIN_URL,
                data={"username": self.username, "password": self.password},
                headers={"X-Application": self.app_key},
                cert=cert,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("loginStatus") == "SUCCESS":
                self.session_token = data["sessionToken"]
                logger.info("Betfair login successful")
                return True
            else:
                logger.error(f"Betfair login failed: {data.get('loginStatus')}")
                return False
        except Exception as e:
            logger.error(f"Betfair login error: {e}")
            return False

    def _headers(self) -> dict:
        return {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _api_call(self, operation: str, params: dict) -> dict | list | None:
        """Make a Betfair API-NG call."""
        if not self.session_token:
            logged_in = await self._login()
            if not logged_in:
                return None

        url = f"{BETTING_URL}/{operation}/"
        try:
            resp = await self.client.post(
                url,
                json={"filter": params} if operation == "listMarketCatalogue" else params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.info("Betfair session expired, re-authenticating")
                await self._login()
                return await self._api_call(operation, params)
            logger.error(f"Betfair API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Betfair API call failed: {e}")
            return None

    async def get_active_markets(self, limit: int = 50) -> list[Market]:
        # Fetch market catalogue — politics, specials, and current affairs
        event_type_ids = ["2378961"]  # Politics. Add more as needed.
        catalogue = await self._api_call("listMarketCatalogue", {
            "filter": {
                "eventTypeIds": event_type_ids,
                "inPlayOnly": False,
                "marketBettingTypes": ["ODDS"],
            },
            "maxResults": str(limit),
            "marketProjection": [
                "MARKET_DESCRIPTION",
                "RUNNER_DESCRIPTION",
                "MARKET_START_TIME",
                "EVENT",
            ],
        })

        if not catalogue:
            logger.warning("No Betfair markets returned (may need auth)")
            return []

        # Get prices for these markets
        market_ids = [m["marketId"] for m in catalogue]
        prices = await self._get_prices(market_ids)

        markets = []
        for cat_market in catalogue:
            mid = cat_market["marketId"]
            runners = cat_market.get("runners", [])
            price_data = prices.get(mid, {})

            outcomes = []
            outcome_prices = []
            for runner in runners:
                outcomes.append(runner.get("runnerName", "Unknown"))
                runner_prices = price_data.get(runner["selectionId"], {})
                back_price = runner_prices.get("back", 0)
                prob = (1.0 / back_price) if back_price > 0 else 0
                outcome_prices.append(round(prob, 4))

            volume = price_data.get("totalMatched", 0)
            desc = cat_market.get("description", {})

            markets.append(Market(
                id=f"betfair_{mid}",
                platform="betfair",
                question=cat_market.get("marketName", ""),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                volume=volume,
                liquidity=price_data.get("totalAvailable", 0),
                category=cat_market.get("event", {}).get("name", ""),
                end_date=desc.get("marketTime", ""),
                url=f"https://www.betfair.com/exchange/plus/market/{mid}",
                description=desc.get("rules", "")[:500] if desc.get("rules") else "",
                extra_data={
                    "market_id": mid,
                    "runners": [
                        {"id": r["selectionId"], "name": r.get("runnerName", "")}
                        for r in runners
                    ],
                },
            ))

        logger.info(f"Fetched {len(markets)} Betfair markets")
        return markets

    async def _get_prices(self, market_ids: list[str]) -> dict:
        """Get current back/lay prices for markets."""
        if not market_ids:
            return {}

        data = await self._api_call("listMarketBook", {
            "marketIds": market_ids,
            "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
        })

        if not data:
            return {}

        result = {}
        for book in data:
            mid = book["marketId"]
            market_prices = {
                "totalMatched": book.get("totalMatched", 0),
                "totalAvailable": book.get("totalAvailable", 0),
            }
            for runner in book.get("runners", []):
                sid = runner["selectionId"]
                ex = runner.get("ex", {})
                best_back = ex.get("availableToBack", [{}])
                best_lay = ex.get("availableToLay", [{}])
                market_prices[sid] = {
                    "back": best_back[0].get("price", 0) if best_back else 0,
                    "lay": best_lay[0].get("price", 0) if best_lay else 0,
                    "back_size": best_back[0].get("size", 0) if best_back else 0,
                    "lay_size": best_lay[0].get("size", 0) if best_lay else 0,
                }
            result[mid] = market_prices
        return result

    async def get_market_details(self, market_id: str) -> Market | None:
        raw_id = market_id.replace("betfair_", "")
        catalogue = await self._api_call("listMarketCatalogue", {
            "filter": {"marketIds": [raw_id]},
            "maxResults": "1",
            "marketProjection": [
                "MARKET_DESCRIPTION", "RUNNER_DESCRIPTION",
                "MARKET_START_TIME", "EVENT",
            ],
        })
        if not catalogue:
            return None
        prices = await self._get_prices([raw_id])
        cat = catalogue[0]
        runners = cat.get("runners", [])
        price_data = prices.get(raw_id, {})

        outcomes = []
        outcome_prices = []
        for r in runners:
            outcomes.append(r.get("runnerName", "Unknown"))
            rp = price_data.get(r["selectionId"], {})
            back = rp.get("back", 0)
            outcome_prices.append(round(1.0 / back, 4) if back > 0 else 0)

        desc = cat.get("description", {})
        return Market(
            id=market_id,
            platform="betfair",
            question=cat.get("marketName", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            volume=price_data.get("totalMatched", 0),
            liquidity=price_data.get("totalAvailable", 0),
            category=cat.get("event", {}).get("name", ""),
            end_date=desc.get("marketTime", ""),
            url=f"https://www.betfair.com/exchange/plus/market/{raw_id}",
            description=desc.get("rules", "")[:500] if desc.get("rules") else "",
            extra_data={
                "market_id": raw_id,
                "runners": [
                    {"id": r["selectionId"], "name": r.get("runnerName", "")}
                    for r in runners
                ],
            },
        )

    async def place_order(self, order: Order) -> OrderResult:
        if not self.session_token:
            return OrderResult(success=False, message="Not authenticated with Betfair")

        raw_market_id = order.market_id.replace("betfair_", "")
        # Find the selection ID from extra_data
        side = "BACK" if order.side == "back" else "LAY"

        data = await self._api_call("placeOrders", {
            "marketId": raw_market_id,
            "instructions": [{
                "selectionId": order.extra_data.get("selection_id") if hasattr(order, "extra_data") else 0,
                "side": side,
                "orderType": "LIMIT",
                "limitOrder": {
                    "size": round(order.stake, 2),
                    "price": round(order.price, 2),
                    "persistenceType": "LAPSE",
                },
            }],
        })

        if not data:
            return OrderResult(success=False, message="API call failed")

        status = data.get("status", "FAILURE")
        if status == "SUCCESS":
            reports = data.get("instructionReports", [{}])
            report = reports[0] if reports else {}
            return OrderResult(
                success=True,
                order_id=str(report.get("betId", "")),
                filled_price=report.get("averagePriceMatched", order.price),
                filled_stake=report.get("sizeMatched", order.stake),
            )
        else:
            error = data.get("errorCode", "Unknown error")
            return OrderResult(success=False, message=f"Betfair: {error}")

    async def close(self) -> None:
        await self.client.aclose()
