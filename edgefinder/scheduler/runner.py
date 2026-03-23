"""Autonomous pipeline runner — the core loop that makes money while you sleep."""

import logging
from datetime import datetime, timezone

from ..analysis.engine import AnalysisEngine
from ..db.database import db_session, insert_analysis, upsert_market
from ..execution.base import Executor
from ..platforms.base import Platform
from ..strategy.edge import detect_edges
from ..strategy.portfolio import check_resolutions
from ..strategy.risk import size_positions

logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(
        self,
        platforms: dict[str, Platform],
        analysis_engine: AnalysisEngine,
        executor: Executor,
        config: dict,
    ):
        self.platforms = platforms
        self.engine = analysis_engine
        self.executor = executor
        self.config = config
        self.run_count = 0

    async def run(self) -> dict:
        """Execute the full pipeline once.

        Steps:
        1. Fetch markets from all platforms
        2. Analyze markets with AI
        3. Detect edges
        4. Size positions
        5. Execute trades
        6. Check for resolved markets
        7. Log everything

        Returns:
            Summary dict of the run
        """
        self.run_count += 1
        start = datetime.now(timezone.utc)
        logger.info(f"=== Pipeline run #{self.run_count} starting at {start.isoformat()} ===")

        summary = {
            "run": self.run_count,
            "started_at": start.isoformat(),
            "markets_fetched": 0,
            "markets_analyzed": 0,
            "edges_found": 0,
            "orders_sized": 0,
            "trades_executed": 0,
            "trades_resolved": 0,
            "errors": [],
        }

        max_markets = self.config.get("schedule", {}).get("max_markets_per_run", 20)

        # Step 1: Fetch markets from all enabled platforms
        all_markets = []
        for name, platform in self.platforms.items():
            try:
                markets = await platform.get_active_markets(limit=max_markets)
                all_markets.extend(markets)
                logger.info(f"Fetched {len(markets)} markets from {name}")
            except Exception as e:
                err = f"Failed to fetch from {name}: {e}"
                logger.error(err)
                summary["errors"].append(err)

        summary["markets_fetched"] = len(all_markets)
        if not all_markets:
            logger.warning("No markets fetched from any platform")
            return summary

        # Limit total markets to analyze
        all_markets = all_markets[:max_markets]

        # Step 2: Store markets in DB
        with db_session() as conn:
            for market in all_markets:
                upsert_market(conn, market.to_dict())

        # Step 3: Analyze markets with AI
        try:
            analyses = await self.engine.analyze_markets(all_markets)
            summary["markets_analyzed"] = len(analyses)
        except Exception as e:
            err = f"Analysis engine failed: {e}"
            logger.error(err)
            summary["errors"].append(err)
            analyses = []

        # Store analyses in DB
        with db_session() as conn:
            for a in analyses:
                insert_analysis(conn, {
                    "market_id": a.market_id,
                    "estimated_probability": a.estimated_probability,
                    "confidence": a.confidence,
                    "edge": a.edge,
                    "reasoning": a.reasoning,
                    "news_context": a.news_context,
                    "model": a.model,
                })

        # Step 4: Detect edges
        risk_config = self.config.get("risk", {})
        opportunities = detect_edges(
            markets=all_markets,
            analyses=analyses,
            min_edge=risk_config.get("min_edge_threshold", 0.10),
            min_confidence=self.config.get("analysis", {}).get("min_confidence", 0.6),
        )
        summary["edges_found"] = len(opportunities)

        if opportunities:
            logger.info("Top opportunities:")
            for i, opp in enumerate(opportunities[:5]):
                logger.info(
                    f"  {i+1}. [{opp.side.upper()}] {opp.outcome} @ "
                    f"{opp.market_price:.1%} → {opp.target_price:.1%} "
                    f"(edge: {opp.abs_edge:.1%}) | {opp.market.question[:50]}"
                )

        # Step 5: Size positions
        orders = size_positions(opportunities, risk_config)
        summary["orders_sized"] = len(orders)

        # Step 6: Execute trades
        if orders:
            results = await self.executor.execute_batch(orders)
            successful = [r for r in results if r.success]
            summary["trades_executed"] = len(successful)
            for r in results:
                if not r.success:
                    summary["errors"].append(f"Trade failed: {r.message}")

        # Step 7: Check for resolved markets
        try:
            resolved = await check_resolutions(self.platforms)
            summary["trades_resolved"] = resolved
        except Exception as e:
            err = f"Resolution check failed: {e}"
            logger.error(err)
            summary["errors"].append(err)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        summary["duration_seconds"] = round(elapsed, 1)
        logger.info(
            f"=== Pipeline run #{self.run_count} complete in {elapsed:.1f}s | "
            f"Fetched: {summary['markets_fetched']}, "
            f"Analyzed: {summary['markets_analyzed']}, "
            f"Edges: {summary['edges_found']}, "
            f"Traded: {summary['trades_executed']} ==="
        )
        return summary
