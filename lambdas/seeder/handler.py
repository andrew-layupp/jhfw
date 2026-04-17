"""
seeder/handler.py — Manually invokable Lambda.
Seeds 6 months of historical data into DynamoDB using real yfinance data.
Adapted from backend/seed.py — identical scoring logic, DynamoDB storage.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

import dynamo_db
from collectors.markets import fetch_markets_history
from scorer import norm, clamp, get_label, WEIGHTS

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# ── Known event anchors for geo + trade (manually calibrated) ─────────────────
# Format: (date_str, geo_delta, trade_delta)
EVENT_ANCHORS = [
    ("2025-11-24",   -5,        -5),   # RBA cuts complete — mild calm
    ("2026-02-04",   +8,        +6),   # RBA hikes 3.85% — tension rises
    ("2026-03-04",  +18,       +10),   # Iran closes Strait of Hormuz
    ("2026-03-18",   +5,        +8),   # RBA hikes to 4.10%
    ("2026-04-02",   +4,       +14),   # Liberation Day tariff anniversary
    ("2026-04-10",   -4,        -3),   # US-Iran ceasefire
]


def _base_geo(vix: float) -> float:
    return clamp(55 + (vix - 20) * 0.8)


def _base_trade(vix: float) -> float:
    return clamp(50 + (vix - 20) * 0.7)


def _event_delta(date: datetime, col: str) -> float:
    total = 0.0
    for anchor_str, geo_d, trade_d in EVENT_ANCHORS:
        anchor = datetime.strptime(anchor_str, "%Y-%m-%d")
        dist   = abs((date - anchor).days)
        if dist <= 14:
            weight = max(0, 1 - dist / 14)
            total += (geo_d if col == "geo" else trade_d) * weight
    return total


async def _seed() -> dict:
    import pandas as pd

    n = dynamo_db.count_snapshots()
    if n >= 10:
        log.info("DB already seeded (%d snapshots) — skipping.", n)
        return {"seeded": 0, "skipped": True, "existing": n}

    log.info("Empty DB — seeding 6 months of history from yfinance...")
    end   = datetime.utcnow()
    start = end - timedelta(days=185)

    frames = await fetch_markets_history(start, end)

    if "vix" not in frames:
        log.warning("Could not fetch VIX history — skipping seed.")
        return {"seeded": 0, "error": "VIX history unavailable"}

    vix_s   = frames.get("vix",    pd.Series(dtype=float))
    spy_s   = frames.get("spy",    pd.Series(dtype=float))
    oil_s   = frames.get("oil",    pd.Series(dtype=float))
    gold_s  = frames.get("gold",   pd.Series(dtype=float))
    aud_s   = frames.get("audusd", pd.Series(dtype=float))

    def weekly(s):
        return s.resample("W-MON").last().dropna()

    vix_w  = weekly(vix_s)
    spy_w  = weekly(spy_s)
    oil_w  = weekly(oil_s)
    gold_w = weekly(gold_s)
    aud_w  = weekly(aud_s)

    inserted = 0
    for ts in vix_w.index:
        date = ts.to_pydatetime()
        try:
            vix    = float(vix_w[ts])
            spy    = float(spy_w.get(ts, 0) or 0)
            oil    = float(oil_w.get(ts, 80) or 80)
            gold   = float(gold_w.get(ts, 1800) or 1800)
            audusd = float(aud_w.get(ts, 0.65) or 0.65)

            # 52-week SPY ATH up to this date
            spy_hist_to_date = spy_s[:ts]
            spy_ath = float(spy_hist_to_date.tail(252).max()) if not spy_hist_to_date.empty else spy
            spy_drawdown = max(0, (spy_ath - spy) / spy_ath * 100) if spy_ath else 0

            # Gold 1Y change
            gold_hist   = gold_s[:ts]
            gold_1y     = float(gold_hist.iloc[0]) if len(gold_hist) >= 200 else gold * 0.85
            gold_1y_pct = (gold - gold_1y) / gold_1y * 100 if gold_1y else 15

            # Oil 30d change
            oil_hist    = oil_s[:ts]
            oil_30d     = float(oil_hist.iloc[-22]) if len(oil_hist) >= 22 else oil * 0.95
            oil_30d_pct = (oil - oil_30d) / oil_30d * 100 if oil_30d else 0

            # ── Score each dimension ────────────────────────────────────────────
            vix_sc  = norm(vix,          10,  65)
            draw_sc = norm(spy_drawdown,  0,  30)
            gold_sc = norm(gold_1y_pct, -10,  60)
            markets = clamp(vix_sc * 0.50 + draw_sc * 0.35 + gold_sc * 0.15)

            oil_lvl = norm(oil, 60, 130)
            oil_chg = norm(oil_30d_pct, -10, 40)
            energy  = clamp(oil_lvl * 0.60 + oil_chg * 0.40)

            geo     = clamp(_base_geo(vix)   + _event_delta(date, "geo"))
            trade   = clamp(_base_trade(vix) + _event_delta(date, "trade"))
            climate = 65.0
            living  = clamp(55 + (date - start).days / 185 * 15)

            overall = round(
                geo * WEIGHTS["geo"] + energy  * WEIGHTS["energy"] +
                trade * WEIGHTS["trade"] + markets * WEIGHTS["markets"] +
                climate * WEIGHTS["climate"] + living * WEIGHTS["living"], 1
            )

            dynamo_db.insert_snapshot({
                "ts":      date.strftime("%Y-%m-%dT%H:00:00"),
                "overall": overall,
                "scores": {
                    "geo":     round(geo, 1),
                    "markets": round(markets, 1),
                    "energy":  round(energy, 1),
                    "trade":   round(trade, 1),
                    "climate": round(climate, 1),
                    "living":  round(living, 1),
                },
                "raw": {
                    "vix":    round(vix, 2),
                    "oil":    round(oil, 2),
                    "gold":   round(gold, 2),
                    "spy":    round(spy, 2),
                    "audusd": round(audusd, 4),
                },
            })
            inserted += 1
        except Exception as e:
            log.warning("Seed error at %s: %s", ts, e)

    log.info("Seed complete — inserted %d weekly snapshots.", inserted)
    return {"seeded": inserted}


def lambda_handler(event, context):
    try:
        result = asyncio.run(_seed())
        return {
            "statusCode": 200,
            "body": json.dumps(result),
        }
    except Exception as e:
        log.error("Seeder failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
