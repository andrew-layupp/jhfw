"""
FRED collector — fetches macro-economic indicators from the Federal Reserve
Economic Data API (https://fred.stlouisfed.org/).
Requires env var FRED_API_KEY.  Returns empty dict gracefully if not set.
"""
import os
import logging
import httpx

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "CPIAUCSL":  "us_cpi",        # US CPI (seasonally adjusted, monthly)
    "FEDFUNDS":  "fed_rate",       # Federal Funds Rate
    "CSUSHPISA": "case_shiller",   # Case-Shiller US National Home Price Index
    "DGS2":      "yield_2y",       # 2-Year Treasury Yield
    "DGS10":     "yield_10y",      # 10-Year Treasury Yield
}


async def _fetch_latest(client: httpx.AsyncClient, series_id: str, api_key: str) -> float | None:
    """Fetch the most recent observation for a FRED series."""
    try:
        r = await client.get(
            FRED_BASE,
            params={
                "series_id":       series_id,
                "api_key":         api_key,
                "file_type":       "json",
                "sort_order":      "desc",
                "limit":           1,
            },
            timeout=20,
        )
        r.raise_for_status()
        observations = r.json().get("observations", [])
        if not observations:
            return None
        value = observations[0].get("value")
        if value is None or value == ".":
            return None
        return round(float(value), 4)
    except Exception as e:
        log.warning("FRED fetch error for %s: %s", series_id, e)
        return None


async def fetch_fred() -> dict:
    """Return latest FRED macro indicators. Empty dict if no API key."""
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        log.info("FRED_API_KEY not set — skipping FRED collector")
        return {}

    result = {}
    async with httpx.AsyncClient() as client:
        for series_id, key_name in SERIES.items():
            val = await _fetch_latest(client, series_id, api_key)
            if val is not None:
                result[key_name] = val

    # Calculate 2Y-10Y yield spread (negative = inverted = recession signal)
    yield_2y = result.get("yield_2y")
    yield_10y = result.get("yield_10y")
    if yield_2y is not None and yield_10y is not None:
        result["yield_spread"] = round(yield_2y - yield_10y, 4)

    log.info("FRED — %s", {k: v for k, v in result.items()})
    return result
