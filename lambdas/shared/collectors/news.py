"""
GDELT collector — uses the free GDELT Doc 2.0 API (no API key).
Measures article volume for:
  • conflict / geopolitical tension keywords
  • trade war / tariff keywords
Normalises each against a 90-day rolling baseline stored in the DB.

Falls back to NewsAPI (https://newsapi.org/) if GDELT fails completely
and NEWSAPI_KEY env var is set.
"""
import asyncio
import os
import httpx
import logging
from datetime import datetime, timedelta
from statistics import mean

log = logging.getLogger(__name__)

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

CONFLICT_QUERY = (
    "war OR conflict OR missile OR airstrike OR nuclear OR troops OR ceasefire "
    "OR casualties OR military OR escalation OR invasion"
)
TRADE_QUERY = (
    'tariff OR "trade war" OR sanctions OR embargo OR "trade deal" OR "import duty" '
    'OR "executive order" OR "Liberation Day" OR Trump'
)


async def _timeline_volume(client: httpx.AsyncClient, query: str, days: int = 7) -> float | None:
    """Sum GDELT article volume for a query over the past `days` days.
    Retries once on HTTP 429 after a 2-second wait."""
    end   = datetime.utcnow()
    start = end - timedelta(days=days)
    params = {
        "query":         query,
        "mode":          "timelineraw",
        "format":        "json",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime":   end.strftime("%Y%m%d%H%M%S"),
        "smoothing":     3,
    }
    for attempt in range(2):
        try:
            r = await client.get(GDELT_DOC, params=params, timeout=30)
            if r.status_code == 429 and attempt == 0:
                log.warning("GDELT 429 — retrying in 2 s")
                await asyncio.sleep(2)
                continue
            data = r.json()
            points = data.get("timeline", [])
            return sum(float(p.get("value", 0)) for p in points)
        except Exception as e:
            log.warning("GDELT timeline error: %s", e)
            return None
    return None


async def _top_articles(client: httpx.AsyncClient, query: str, n: int = 5) -> list[dict]:
    """Fetch the top N recent articles matching a query."""
    try:
        r = await client.get(
            GDELT_DOC,
            params={
                "query":      query,
                "mode":       "artlist",
                "maxrecords": n,
                "format":     "json",
                "sortby":     "date",
            },
            timeout=20,
        )
        arts = r.json().get("articles", [])
        return [
            {
                "title":  a.get("title", "")[:140],
                "url":    a.get("url", ""),
                "source": a.get("domain", ""),
                "ts":     a.get("seendate", ""),
            }
            for a in arts
        ]
    except Exception as e:
        log.warning("GDELT artlist error: %s", e)
        return []


NEWSAPI_BASE = "https://newsapi.org/v2/everything"

NEWSAPI_QUERIES = {
    "conflict": "war OR conflict OR missile OR airstrike OR nuclear OR troops",
    "trade":    "tariff OR trade war OR sanctions OR embargo OR trade deal",
}


async def _newsapi_ratio(client: httpx.AsyncClient, query: str, api_key: str) -> float | None:
    """Compute 7d-vs-30d article-count ratio from NewsAPI for a query."""
    now = datetime.utcnow()
    try:
        # 7-day count
        r7 = await client.get(
            NEWSAPI_BASE,
            params={
                "q":        query,
                "from":     (now - timedelta(days=7)).strftime("%Y-%m-%d"),
                "to":       now.strftime("%Y-%m-%d"),
                "sortBy":   "publishedAt",
                "pageSize": 1,
                "apiKey":   api_key,
            },
            timeout=20,
        )
        total_7d = r7.json().get("totalResults", 0)

        # 30-day count
        r30 = await client.get(
            NEWSAPI_BASE,
            params={
                "q":        query,
                "from":     (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                "to":       now.strftime("%Y-%m-%d"),
                "sortBy":   "publishedAt",
                "pageSize": 1,
                "apiKey":   api_key,
            },
            timeout=20,
        )
        total_30d = r30.json().get("totalResults", 0)

        if total_30d == 0:
            return None
        # Normalise to daily rates then compute ratio
        rate_7d  = total_7d / 7
        rate_30d = total_30d / 30
        return round(rate_7d / rate_30d, 3) if rate_30d else None
    except Exception as e:
        log.warning("NewsAPI error for query '%s': %s", query, e)
        return None


async def _newsapi_signals(client: httpx.AsyncClient, api_key: str) -> list[dict]:
    """Fetch top recent articles from NewsAPI for signal headlines."""
    try:
        r = await client.get(
            NEWSAPI_BASE,
            params={
                "q":        "geopolitical OR tariff OR sanctions OR conflict",
                "sortBy":   "publishedAt",
                "pageSize": 5,
                "apiKey":   api_key,
            },
            timeout=20,
        )
        articles = r.json().get("articles", [])
        return [
            {
                "title":    a.get("title", "")[:140],
                "url":      a.get("url", ""),
                "source":   (a.get("source") or {}).get("name", ""),
                "ts":       a.get("publishedAt", ""),
                "category": "newsapi",
            }
            for a in articles
        ]
    except Exception as e:
        log.warning("NewsAPI signals error: %s", e)
        return []


async def fetch_news() -> dict:
    """Return conflict + trade article volumes (7d and 90d) plus top headlines.
    Falls back to NewsAPI if GDELT returns only defaults and NEWSAPI_KEY is set."""
    async with httpx.AsyncClient() as client:
        # Current 7-day window
        conflict_7d = await _timeline_volume(client, CONFLICT_QUERY, days=7)
        trade_7d    = await _timeline_volume(client, TRADE_QUERY,    days=7)

        # 90-day baseline (for normalisation)
        conflict_90d = await _timeline_volume(client, CONFLICT_QUERY, days=90)
        trade_90d    = await _timeline_volume(client, TRADE_QUERY,    days=90)

        # Top headlines for the signals feed
        conflict_headlines = await _top_articles(client, CONFLICT_QUERY, n=4)
        trade_headlines    = await _top_articles(client, TRADE_QUERY,    n=3)

    def daily_rate(vol, days):
        return vol / days if vol else None

    c7  = daily_rate(conflict_7d,  7)
    c90 = daily_rate(conflict_90d, 90)
    t7  = daily_rate(trade_7d,  7)
    t90 = daily_rate(trade_90d, 90)

    # Ratio vs baseline  (>1 = elevated above 90-day average)
    conflict_ratio = (c7  / c90)  if (c7  and c90)  else 1.0
    trade_ratio    = (t7  / t90)  if (t7  and t90)  else 1.0

    log.info("GDELT — conflict ratio %.2f | trade ratio %.2f", conflict_ratio, trade_ratio)

    signals = []
    for h in conflict_headlines:
        signals.append({**h, "category": "geopolitical"})
    for h in trade_headlines:
        signals.append({**h, "category": "trade"})

    # ------------------------------------------------------------------
    # NewsAPI fallback: if GDELT returned only defaults (both ratios 1.0)
    # and NEWSAPI_KEY is available, try NewsAPI as a backup source.
    # ------------------------------------------------------------------
    gdelt_failed = (conflict_ratio == 1.0 and trade_ratio == 1.0)
    newsapi_key = os.environ.get("NEWSAPI_KEY", "").strip()

    if gdelt_failed and newsapi_key:
        log.info("GDELT returned defaults — falling back to NewsAPI")
        async with httpx.AsyncClient() as client:
            na_conflict = await _newsapi_ratio(client, NEWSAPI_QUERIES["conflict"], newsapi_key)
            na_trade    = await _newsapi_ratio(client, NEWSAPI_QUERIES["trade"],    newsapi_key)
            na_signals  = await _newsapi_signals(client, newsapi_key)

        if na_conflict is not None:
            conflict_ratio = na_conflict
        if na_trade is not None:
            trade_ratio = na_trade
        if na_signals:
            signals.extend(na_signals)

        log.info("NewsAPI — conflict ratio %.2f | trade ratio %.2f",
                 conflict_ratio, trade_ratio)

    return {
        "conflict_7d_rate":  c7,
        "conflict_90d_rate": c90,
        "conflict_ratio":    round(conflict_ratio, 3),
        "trade_7d_rate":     t7,
        "trade_90d_rate":    t90,
        "trade_ratio":       round(trade_ratio, 3),
        "signals":           signals,
    }
