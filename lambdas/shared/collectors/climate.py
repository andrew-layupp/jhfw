"""
Climate collector — Open-Meteo archive + forecast APIs (no API key).
Computes a global mean temperature anomaly (current vs 1991-2020 baseline).
"""
import httpx
import logging
from datetime import datetime, timedelta
from statistics import mean

log = logging.getLogger(__name__)

# Representative global cities (spread across hemispheres & continents)
CITIES = [
    {"name": "Sydney",      "lat": -33.87, "lon":  151.21},
    {"name": "London",      "lat":  51.51, "lon":   -0.13},
    {"name": "New York",    "lat":  40.71, "lon":  -74.01},
    {"name": "Tokyo",       "lat":  35.68, "lon":  139.69},
    {"name": "Delhi",       "lat":  28.66, "lon":   77.23},
    {"name": "Nairobi",     "lat":  -1.29, "lon":   36.82},
    {"name": "São Paulo",   "lat": -23.55, "lon":  -46.63},
    {"name": "Moscow",      "lat":  55.75, "lon":   37.62},
]

BASELINE_YEARS = [1991, 2000]   # sample from this range for the "normal" mean
FORECAST_URL  = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL   = "https://archive-api.open-meteo.com/v1/archive"


async def _get_mean_temp(client: httpx.AsyncClient, url: str, params: dict) -> float | None:
    try:
        r = await client.get(url, params=params, timeout=20)
        data = r.json()
        temps = [t for t in data.get("daily", {}).get("temperature_2m_mean", []) if t is not None]
        return mean(temps) if temps else None
    except Exception as e:
        log.warning("Open-Meteo error: %s", e)
        return None


async def fetch_climate() -> dict:
    today = datetime.utcnow()
    week_ago = today - timedelta(days=7)

    # Same calendar week in multiple past years for baseline
    baseline_temps = []
    current_temps  = []

    async with httpx.AsyncClient() as client:
        for city in CITIES:
            base_params = {
                "latitude":  city["lat"],
                "longitude": city["lon"],
                "daily":     "temperature_2m_mean",
                "timezone":  "UTC",
            }

            # --- current week ---
            t = await _get_mean_temp(client, FORECAST_URL, {
                **base_params,
                "past_days":     7,
                "forecast_days": 0,
            })
            if t is not None:
                current_temps.append(t)

            # --- historical baseline: same week across baseline years ---
            for year in range(BASELINE_YEARS[0], BASELINE_YEARS[1] + 1):
                try:
                    start = datetime(year, week_ago.month, week_ago.day)
                    end   = datetime(year, today.month,    today.day)
                except ValueError:
                    continue   # Feb 29 edge case
                t_hist = await _get_mean_temp(client, ARCHIVE_URL, {
                    **base_params,
                    "start_date": start.strftime("%Y-%m-%d"),
                    "end_date":   end.strftime("%Y-%m-%d"),
                })
                if t_hist is not None:
                    baseline_temps.append(t_hist)

    if not current_temps or not baseline_temps:
        log.warning("Climate: insufficient data")
        return {"anomaly_c": None, "cities_sampled": 0}

    anomaly = mean(current_temps) - mean(baseline_temps)
    log.info("Climate anomaly: %+.2f°C (n=%d cities)", anomaly, len(current_temps))

    return {
        "anomaly_c":      round(anomaly, 3),
        "current_mean_c": round(mean(current_temps), 2),
        "baseline_mean_c":round(mean(baseline_temps), 2),
        "cities_sampled": len(current_temps),
    }
