import aiosqlite
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = "chaos.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL UNIQUE,
    overall   REAL NOT NULL,
    geo       REAL,
    markets   REAL,
    energy    REAL,
    trade     REAL,
    climate   REAL,
    living    REAL,
    vix       REAL,
    oil       REAL,
    gold      REAL,
    spy       REAL,
    audusd    REAL,
    raw       TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    text      TEXT NOT NULL,
    category  TEXT,
    source    TEXT,
    url       TEXT
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    score     INTEGER NOT NULL,
    ip_hash   TEXT,
    country   TEXT NOT NULL DEFAULT 'au',
    factors   TEXT,
    reason    TEXT,
    metadata_only INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_signals_ts   ON signals(ts);
CREATE INDEX IF NOT EXISTS idx_poll_ts      ON poll_votes(ts);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def insert_snapshot(data: dict):
    """Upsert a chaos snapshot (keyed on hourly timestamp)."""
    ts = data.get("ts") or datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO snapshots
               (ts, overall, geo, markets, energy, trade, climate, living,
                vix, oil, gold, spy, audusd, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ts) DO UPDATE SET
                 overall=excluded.overall, geo=excluded.geo,
                 markets=excluded.markets, energy=excluded.energy,
                 trade=excluded.trade, climate=excluded.climate,
                 living=excluded.living, vix=excluded.vix,
                 oil=excluded.oil, gold=excluded.gold,
                 spy=excluded.spy, audusd=excluded.audusd,
                 raw=excluded.raw
            """,
            (
                ts,
                data.get("overall"),
                data["scores"].get("geo"),
                data["scores"].get("markets"),
                data["scores"].get("energy"),
                data["scores"].get("trade"),
                data["scores"].get("climate"),
                data["scores"].get("living"),
                data["raw"].get("vix"),
                data["raw"].get("oil"),
                data["raw"].get("gold"),
                data["raw"].get("spy"),
                data["raw"].get("audusd"),
                json.dumps(data.get("raw", {})),
            ),
        )
        await db.commit()


async def insert_signals(signals: list[dict]):
    """Insert fresh signal rows (deduplicated by text+hour)."""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        for s in signals:
            await db.execute(
                """INSERT OR IGNORE INTO signals (ts, text, category, source, url)
                   VALUES (?,?,?,?,?)""",
                (ts, s["text"], s.get("category"), s.get("source"), s.get("url")),
            )
        await db.commit()


async def get_latest() -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM snapshots ORDER BY ts DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        # Recent signals
        async with db.execute(
            "SELECT text, category, source, url, ts FROM signals ORDER BY id DESC LIMIT 10"
        ) as cur:
            sigs = [dict(r) for r in await cur.fetchall()]

    return _row_to_dict(row, sigs)


async def get_history(days: int = 180) -> list[dict]:
    """Return one snapshot per day (latest of that day) for the past N days."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date(ts) as day,
                      ts, overall, geo, markets, energy, trade, climate, living,
                      vix, oil, gold, spy, audusd
               FROM snapshots
               WHERE ts >= ?
               GROUP BY day
               ORDER BY day ASC""",
            (since,),
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def count_snapshots() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM snapshots") as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def insert_poll_vote(score: int, ip_hash: str = None, country: str = "au",
                           factors: list = None, reason: str = None,
                           metadata_only: bool = False):
    """Insert a user poll vote with optional factor selections and reason."""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO poll_votes (ts, score, ip_hash, country, factors, reason, metadata_only) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, score, ip_hash, country,
             json.dumps(factors) if factors else None,
             reason[:140] if reason else None,
             1 if metadata_only else 0),
        )
        await db.commit()


async def get_recent_votes(country: str = "au", limit: int = 20) -> list:
    """Return recent votes that include factor selections, for the ticker."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT ts, score, factors, reason, country FROM poll_votes
               WHERE country = ? AND factors IS NOT NULL
               ORDER BY ts DESC LIMIT ?""",
            (country, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [{"ts": r["ts"], "score": r["score"],
             "factors": json.loads(r["factors"]) if r["factors"] else [],
             "reason": r["reason"], "country": r["country"]} for r in rows]


async def get_poll_results(country: str = "au") -> dict:
    """Return aggregate poll results for a specific country."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT score, COUNT(*) as cnt FROM poll_votes WHERE country = ? AND metadata_only = 0 GROUP BY score",
            (country,),
        ) as cur:
            rows = await cur.fetchall()
    distribution = {i: 0 for i in range(1, 11)}
    total = 0
    weighted_sum = 0
    for score_val, cnt in rows:
        distribution[score_val] = cnt
        total += cnt
        weighted_sum += score_val * cnt
    average = round(weighted_sum / total, 2) if total > 0 else 0.0
    return {"total_votes": total, "average": average, "distribution": distribution}


def _row_to_dict(row, signals=None) -> dict:
    d = dict(row)
    scores = {
        "geo":     d.pop("geo", None),
        "markets": d.pop("markets", None),
        "energy":  d.pop("energy", None),
        "trade":   d.pop("trade", None),
        "climate": d.pop("climate", None),
        "living":  d.pop("living", None),
    }
    raw_str = d.pop("raw", None)
    raw = json.loads(raw_str) if raw_str else {}
    result = {**d, "scores": scores, "raw": raw}
    if signals is not None:
        result["signals"] = signals
    return result
