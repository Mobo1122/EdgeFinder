#!/usr/bin/env python3
"""EdgeFinder Agent — AI-powered prediction market edge detection.

Monitors Betfair, Smarkets, and Manifold Markets for mispriced outcomes,
uses Claude AI to estimate true probabilities, and trades automatically.

Usage:
    python main.py              # Start with paper trading (default)
    python main.py --once       # Run pipeline once then exit
    python main.py --live       # Start with live trading (careful!)
    python main.py --dashboard  # Dashboard only, no trading
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
import yaml
from dotenv import load_dotenv

from edgefinder.analysis.engine import AnalysisEngine
from edgefinder.dashboard.app import create_dashboard
from edgefinder.db.database import init_db
from edgefinder.execution.live import LiveExecutor
from edgefinder.execution.paper import PaperExecutor
from edgefinder.platforms.betfair import BetfairPlatform
from edgefinder.platforms.manifold import ManifoldPlatform
from edgefinder.platforms.smarkets import SmarketsPlatform
from edgefinder.scheduler.runner import PipelineRunner

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edgefinder")


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def create_platforms(config: dict) -> dict:
    """Initialize enabled platform connectors."""
    platforms = {}
    platform_config = config.get("platforms", {})

    # Manifold — always available, no auth needed for reading
    if platform_config.get("manifold", {}).get("enabled", True):
        platforms["manifold"] = ManifoldPlatform(
            config=platform_config["manifold"],
            api_key=os.getenv("MANIFOLD_API_KEY", ""),
        )
        logger.info("Manifold Markets connector enabled")

    # Betfair
    if platform_config.get("betfair", {}).get("enabled", True):
        platforms["betfair"] = BetfairPlatform(
            config=platform_config["betfair"],
            app_key=os.getenv("BETFAIR_APP_KEY", ""),
            username=os.getenv("BETFAIR_USERNAME", ""),
            password=os.getenv("BETFAIR_PASSWORD", ""),
            cert_path=os.getenv("BETFAIR_CERT_PATH", ""),
            key_path=os.getenv("BETFAIR_KEY_PATH", ""),
        )
        logger.info("Betfair Exchange connector enabled")

    # Smarkets
    if platform_config.get("smarkets", {}).get("enabled", True):
        platforms["smarkets"] = SmarketsPlatform(
            config=platform_config["smarkets"],
            api_token=os.getenv("SMARKETS_API_TOKEN", ""),
        )
        logger.info("Smarkets connector enabled")

    return platforms


async def run_once(config: dict) -> dict:
    """Run the pipeline a single time."""
    platforms = create_platforms(config)
    engine = AnalysisEngine(config.get("analysis", {}))

    mode = config.get("mode", "paper")
    if mode == "live":
        executor = LiveExecutor(platforms)
    else:
        executor = PaperExecutor()

    runner = PipelineRunner(platforms, engine, executor, config)
    try:
        summary = await runner.run()
        return summary
    finally:
        for p in platforms.values():
            await p.close()


async def run_scheduled(config: dict, pipeline_state: dict) -> None:
    """Run the pipeline on a recurring schedule."""
    interval_hours = config.get("schedule", {}).get("interval_hours", 2)
    interval_seconds = interval_hours * 3600

    platforms = create_platforms(config)
    engine = AnalysisEngine(config.get("analysis", {}))

    mode = config.get("mode", "paper")
    if mode == "live":
        executor = LiveExecutor(platforms)
    else:
        executor = PaperExecutor()

    runner = PipelineRunner(platforms, engine, executor, config)

    logger.info(f"Scheduler started — running every {interval_hours} hours in {mode.upper()} mode")

    try:
        while True:
            try:
                summary = await runner.run()
                pipeline_state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                pipeline_state["run_count"] = runner.run_count
                pipeline_state["last_summary"] = summary
            except Exception as e:
                logger.error(f"Pipeline run failed: {e}")

            logger.info(f"Next run in {interval_hours} hours...")
            await asyncio.sleep(interval_seconds)
    finally:
        for p in platforms.values():
            await p.close()


def start_dashboard(config: dict, pipeline_state: dict) -> None:
    """Start the dashboard in a separate thread."""
    dashboard_config = config.get("dashboard", {})
    app = create_dashboard(config, pipeline_state)
    uvicorn.run(
        app,
        host=dashboard_config.get("host", "0.0.0.0"),
        port=dashboard_config.get("port", 8080),
        log_level="warning",
    )


def main():
    parser = argparse.ArgumentParser(description="EdgeFinder Agent")
    parser.add_argument("--once", action="store_true", help="Run pipeline once then exit")
    parser.add_argument("--live", action="store_true", help="Enable live trading (careful!)")
    parser.add_argument("--dashboard", action="store_true", help="Dashboard only, no trading")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable the web dashboard")
    args = parser.parse_args()

    config = load_config()

    # Override mode if --live flag
    if args.live:
        config["mode"] = "live"
        logger.warning("LIVE TRADING MODE ENABLED — real money at risk!")

    # Init database
    init_db()
    logger.info("Database initialized")

    mode = config.get("mode", "paper")
    print(f"\n{'='*60}")
    print(f"  EdgeFinder Agent — {mode.upper()} MODE")
    print(f"  Platforms: Betfair, Smarkets, Manifold Markets")
    print(f"  Schedule: Every {config.get('schedule', {}).get('interval_hours', 2)} hours")
    print(f"  Dashboard: http://localhost:{config.get('dashboard', {}).get('port', 8080)}")
    print(f"{'='*60}\n")

    if args.once:
        # Single run
        summary = asyncio.run(run_once(config))
        print(f"\nPipeline complete:")
        print(f"  Markets fetched: {summary.get('markets_fetched', 0)}")
        print(f"  Markets analyzed: {summary.get('markets_analyzed', 0)}")
        print(f"  Edges found: {summary.get('edges_found', 0)}")
        print(f"  Trades executed: {summary.get('trades_executed', 0)}")
        if summary.get("errors"):
            print(f"  Errors: {len(summary['errors'])}")
        return

    # Shared state between scheduler and dashboard
    pipeline_state = {"last_run": None, "run_count": 0, "last_summary": {}}

    if args.dashboard:
        # Dashboard only
        start_dashboard(config, pipeline_state)
        return

    # Start dashboard in background thread
    if not args.no_dashboard:
        dashboard_thread = threading.Thread(
            target=start_dashboard,
            args=(config, pipeline_state),
            daemon=True,
        )
        dashboard_thread.start()
        logger.info(f"Dashboard started on port {config.get('dashboard', {}).get('port', 8080)}")

    # Handle graceful shutdown
    def handle_signal(sig, frame):
        logger.info("Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Run the scheduler
    asyncio.run(run_scheduled(config, pipeline_state))


if __name__ == "__main__":
    main()
