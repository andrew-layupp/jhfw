"""
collectors/__init__.py
Runs all collectors concurrently and merges results.
"""
import asyncio
import logging
from .markets import fetch_markets
from .climate import fetch_climate
from .news    import fetch_news

log = logging.getLogger(__name__)


async def collect_all() -> dict:
    """Fetch all data sources concurrently. Returns merged raw dict."""
    log.info("Starting data collection...")

    results = await asyncio.gather(
        fetch_markets(),
        fetch_climate(),
        fetch_news(),
        return_exceptions=True,
    )

    markets_data, climate_data, news_data = results

    if isinstance(markets_data, Exception):
        log.error("Markets collector failed: %s", markets_data)
        markets_data = {}
    if isinstance(climate_data, Exception):
        log.error("Climate collector failed: %s", climate_data)
        climate_data = {}
    if isinstance(news_data, Exception):
        log.error("News collector failed: %s", news_data)
        news_data = {}

    return {
        "markets": markets_data,
        "climate": climate_data,
        "news":    news_data,
    }
