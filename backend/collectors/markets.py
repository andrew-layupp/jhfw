"""
Markets collector — uses yfinance (no API key required).
Fetches: VIX, S&P 500, Gold, Brent Oil, AUD/USD
"""
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

TICKERS = {
    "vix":    "^VIX",
    "spy":    "SPY",
    "gold":   "GC=F",
    "oil":    "BZ=F",
    "audusd": "AUDUSD=X",
    "dxy":    "DX-Y.NYB",
}


def _safe_float(series, idx=-1) -> float | None:
    try:
        val = series.iloc[idx]
        return round(float(val), 4) if val is not None else None
    except Exception:
        return None


async def fetch_markets() -> dict:
    """Return a dict of current market values + 30-day changes."""
    import yfinance as yf

    result = {}
    for key, ticker in TICKERS.items():
        try:
            hist = yf.download(ticker, period="1y", interval="1d",
                               progress=False, auto_adjust=True)
            if hist.empty:
                log.warning("No data for %s", ticker)
                continue
            close = hist["Close"].dropna()
            current   = _safe_float(close)
            prev_30d  = _safe_float(close, -22)   # ~1 month of trading days
            prev_1y   = _safe_float(close, 0)
            ath_52w   = float(close.tail(252).max())

            change_30d_pct = (
                (current - prev_30d) / prev_30d * 100
                if current and prev_30d else None
            )
            change_1y_pct = (
                (current - prev_1y) / prev_1y * 100
                if current and prev_1y else None
            )
            drawdown_from_ath = (
                (ath_52w - current) / ath_52w * 100
                if current and ath_52w else None
            )

            result[key] = {
                "current":           current,
                "prev_30d":          prev_30d,
                "prev_1y":           prev_1y,
                "ath_52w":           round(ath_52w, 4),
                "change_30d_pct":    round(change_30d_pct, 2) if change_30d_pct is not None else None,
                "change_1y_pct":     round(change_1y_pct, 2)  if change_1y_pct  is not None else None,
                "drawdown_from_ath": round(drawdown_from_ath, 2) if drawdown_from_ath is not None else None,
            }
            log.info("  %s → %.2f (30d: %+.1f%%)", key.upper(),
                     current, change_30d_pct or 0)
        except Exception as e:
            log.error("Error fetching %s: %s", ticker, e)

    return result


async def fetch_markets_history(start: datetime, end: datetime) -> dict:
    """Return daily close prices for the full date range (for seeding)."""
    import yfinance as yf
    import pandas as pd

    frames = {}
    for key, ticker in TICKERS.items():
        try:
            hist = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if not hist.empty:
                frames[key] = hist["Close"].dropna()
        except Exception as e:
            log.warning("History fetch failed for %s: %s", ticker, e)

    return frames
