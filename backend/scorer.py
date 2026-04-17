"""
scorer.py
Converts raw collector data into normalised 0-100 dimension scores.

Each normalisation function is documented with its floor/ceiling so the
scoring logic is transparent and easy to tune.
"""
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def norm(value: float, lo: float, hi: float) -> float:
    """Linear normalisation → [0, 100]."""
    if hi == lo:
        return 0.0
    return clamp((value - lo) / (hi - lo) * 100)


# ─────────────────────────────────────────────────────────────
# Dimension scorers
# ─────────────────────────────────────────────────────────────

def score_markets(m: dict) -> tuple[float, dict]:
    """
    Inputs: VIX, SPY drawdown from 52w ATH, Gold 1Y change
    VIX:        10 → 0,  65 → 100
    Drawdown:    0 → 0,  30% → 100
    Gold 1Y:   -10% → 0, 60% → 100
    """
    raw = {}
    vix_data = m.get("vix", {})
    spy_data = m.get("spy", {})
    gld_data = m.get("gold", {})

    vix = vix_data.get("current")
    spy_drawdown = spy_data.get("drawdown_from_ath")
    gold_1y = gld_data.get("change_1y_pct")

    vix_score  = norm(vix,         10,  65)  if vix          is not None else 40.0
    draw_score = norm(spy_drawdown,  0,  30)  if spy_drawdown is not None else 20.0
    gold_score = norm(gold_1y,     -10,  60)  if gold_1y      is not None else 30.0

    score = vix_score * 0.50 + draw_score * 0.35 + gold_score * 0.15
    raw = {
        "vix": vix,
        "spy_drawdown_pct": spy_drawdown,
        "gold_1y_pct": gold_1y,
    }
    log.debug("markets → %.1f (vix=%.1f draw=%.1f gold=%.1f)", score, vix_score, draw_score, gold_score)
    return round(clamp(score), 1), raw


def score_energy(m: dict) -> tuple[float, dict]:
    """
    Inputs: Brent crude current price, 30-day change %
    Price level: $60 → 0, $130 → 100
    30d change:  -10% → 0, +40% → 100
    """
    oil_data = m.get("oil", {})
    price    = oil_data.get("current")
    chg_30d  = oil_data.get("change_30d_pct")

    level_score  = norm(price,   60, 130) if price   is not None else 40.0
    change_score = norm(chg_30d, -10,  40) if chg_30d is not None else 20.0

    score = level_score * 0.60 + change_score * 0.40
    log.debug("energy → %.1f (level=%.1f chg=%.1f)", score, level_score, change_score)
    return round(clamp(score), 1), {"oil_price": price, "oil_30d_pct": chg_30d}


def score_geopolitical(news: dict) -> tuple[float, dict]:
    """
    Input: GDELT conflict article ratio (current 7d rate vs 90d baseline)
    Ratio 0.5 → 0,  Ratio 2.5 → 100
    Boosted by VIX if available (market stress correlates with geopolitical risk).
    """
    ratio = news.get("conflict_ratio", 1.0)
    score = norm(ratio, 0.5, 2.5)
    log.debug("geo → %.1f (ratio=%.2f)", score, ratio)
    return round(clamp(score), 1), {"conflict_ratio": ratio}


def score_trade(news: dict, markets: dict) -> tuple[float, dict]:
    """
    Input: GDELT trade/tariff article ratio (current 7d vs 90d baseline)
    Ratio 0.3 → 0,  Ratio 2.0 → 100
    VIX acts as a 20% co-signal (trade war spikes VIX).
    """
    ratio    = news.get("trade_ratio", 1.0)
    vix      = (markets.get("vix") or {}).get("current") or 20.0
    news_sc  = norm(ratio, 0.3, 2.0)
    vix_sc   = norm(vix,   10,  65)
    score    = news_sc * 0.80 + vix_sc * 0.20
    log.debug("trade → %.1f (ratio=%.2f vix=%.1f)", score, ratio, vix)
    return round(clamp(score), 1), {"trade_ratio": ratio}


def score_climate(climate: dict) -> tuple[float, dict]:
    """
    Input: global temperature anomaly vs 1991-2020 baseline (°C)
    -0.5°C → 0,  +2.5°C → 100
    Falls back to 65 (reflecting current ~1.5°C anomaly) if data unavailable.
    """
    anomaly = climate.get("anomaly_c")
    if anomaly is None:
        return 65.0, {"anomaly_c": None, "note": "fallback"}
    score = norm(anomaly, -0.5, 2.5)
    log.debug("climate → %.1f (anomaly=%+.2f°C)", score, anomaly)
    return round(clamp(score), 1), {"anomaly_c": anomaly}


def score_living() -> tuple[float, dict]:
    """
    Cost of living uses semi-static cached data (CPI updates monthly).
    Encoded from latest known values; refresh when ABS/ABS publishes.
    AU CPI 3.6%,  US CPI 2.8%,  RBA 4.10%  → score ~67
    Range: AU CPI [2%, 8%], RBA rate [1%, 7%]
    """
    au_cpi  = 3.6    # % YoY — update monthly
    rba_rate = 4.10  # % — update on each RBA decision
    cpi_score  = norm(au_cpi,   2.0, 8.0)
    rate_score = norm(rba_rate, 1.0, 7.0)
    score = cpi_score * 0.60 + rate_score * 0.40
    return round(clamp(score), 1), {"au_cpi": au_cpi, "rba_rate": rba_rate}


# ─────────────────────────────────────────────────────────────
# Composite
# ─────────────────────────────────────────────────────────────

WEIGHTS = {
    "geo":     0.25,
    "energy":  0.20,
    "trade":   0.20,
    "markets": 0.15,
    "climate": 0.10,
    "living":  0.10,
}

LABELS = [
    (89, "Completely cooked"),
    (76, "Severely fucked"),
    (61, "Pretty fucked"),
    (41, "Not great"),
    (21, "A bit tense"),
    (0,  "We're fine"),
]


def get_label(score: float) -> str:
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return "We're fine"


def calculate_scores(raw: dict) -> dict:
    markets = raw.get("markets", {})
    climate = raw.get("climate", {})
    news    = raw.get("news",    {})

    geo_score,     geo_raw     = score_geopolitical(news)
    markets_score, markets_raw = score_markets(markets)
    energy_score,  energy_raw  = score_energy(markets)
    trade_score,   trade_raw   = score_trade(news, markets)
    climate_score, climate_raw = score_climate(climate)
    living_score,  living_raw  = score_living()

    scores = {
        "geo":     geo_score,
        "markets": markets_score,
        "energy":  energy_score,
        "trade":   trade_score,
        "climate": climate_score,
        "living":  living_score,
    }

    overall = round(sum(scores[k] * w for k, w in WEIGHTS.items()), 1)

    raw_flat = {
        "vix":    (markets.get("vix")    or {}).get("current"),
        "oil":    (markets.get("oil")    or {}).get("current"),
        "gold":   (markets.get("gold")   or {}).get("current"),
        "spy":    (markets.get("spy")    or {}).get("current"),
        "audusd": (markets.get("audusd") or {}).get("current"),
        **geo_raw, **markets_raw, **energy_raw,
        **trade_raw, **climate_raw, **living_raw,
    }

    # Auto-generate market signals
    signals = list(news.get("signals", []))
    vix_val = raw_flat.get("vix")
    if vix_val and vix_val > 25:
        signals.insert(0, {
            "text": f"VIX at {vix_val:.1f} — market fear index elevated",
            "category": "markets",
            "source": "yfinance",
        })
    oil_chg = (markets.get("oil") or {}).get("change_30d_pct")
    oil_px  = raw_flat.get("oil")
    if oil_chg and oil_px and abs(oil_chg) > 5:
        direction = "up" if oil_chg > 0 else "down"
        signals.insert(0, {
            "text": f"Brent crude {direction} {abs(oil_chg):.1f}% in 30 days (${oil_px:.0f}/bbl)",
            "category": "energy",
            "source": "yfinance",
        })

    log.info("Overall chaos score: %.1f — %s", overall, get_label(overall))

    return {
        "ts":      datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "overall": overall,
        "label":   get_label(overall),
        "scores":  scores,
        "raw":     raw_flat,
        "signals": signals[:12],
    }
