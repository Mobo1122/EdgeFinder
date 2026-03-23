"""Fetch relevant news/context for market analysis.

Uses a lightweight approach: Claude's built-in knowledge + optional web search.
For production, you could add NewsAPI, Tavily, or similar integrations.
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


async def fetch_news_context(question: str, description: str = "") -> str:
    """Gather context for a market question.

    Currently returns a structured prompt section. In production,
    integrate a news API (NewsAPI, Tavily, etc.) for fresh data.
    """
    context_parts = []

    # Add the current date for temporal awareness
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    context_parts.append(f"Current date/time: {now}")

    # Add market description as context
    if description:
        context_parts.append(f"Market description: {description}")

    # Try to fetch from a free news source (DuckDuckGo instant answers)
    news = await _search_duckduckgo(question)
    if news:
        context_parts.append(f"Relevant search results:\n{news}")
    else:
        context_parts.append(
            "No fresh news fetched — use your training knowledge to assess this market. "
            "Note the current date above for temporal context."
        )

    return "\n\n".join(context_parts)


async def _search_duckduckgo(query: str) -> str:
    """Quick search using DuckDuckGo instant answer API (no auth needed)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
            )
            resp.raise_for_status()
            data = resp.json()

        parts = []
        # Abstract/summary
        if data.get("Abstract"):
            parts.append(data["Abstract"])
        # Related topics
        for topic in (data.get("RelatedTopics") or [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(f"- {topic['Text'][:200]}")

        return "\n".join(parts) if parts else ""
    except Exception as e:
        logger.debug(f"DuckDuckGo search failed: {e}")
        return ""
