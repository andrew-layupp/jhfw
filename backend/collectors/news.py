"""
GDELT collector — uses the free GDELT Doc 2.0 API (no API key).
Measures article volume for:
  • conflict / geopolitical tension keywords
  • trade war / tariff keywords
Normalises each against a 90-day rolling baseline stored in the DB.
"""
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
    """Sum GDELT article volume for a query over the past `days` days."""
    end   = datetime.utcnow()
    start = end - timedelta(days=days)
    try:
        r = await client.get(
            GDELT_DOC,
            params={
                "query":         query,
                "mode":          "timelineraw",
                "format":        "json",
                "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                "enddatetime":   end.strftime("%Y%m%d%H%M%S"),
                "smoothing":     3,
            },
            timeout=30,
        )
        data = r.json()
        points = data.get("timeline", [])
        return sum(float(p.get("value", 0)) for p in points)
    except Exception as e:
        log.warning("GDELT timeline error: %s", e)
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


async def fetch_news() -> dict:
    """Return conflict + trade article volumes (7d and 90d) plus top headlines."""
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

    return {
        "conflict_7d_rate":  c7,
        "conflict_90d_rate": c90,
        "conflict_ratio":    round(conflict_ratio, 3),
        "trade_7d_rate":     t7,
        "trade_90d_rate":    t90,
        "trade_ratio":       round(trade_ratio, 3),
        "signals":           signals,
    }
