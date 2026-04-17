"""
main.py — justhowfuckedarewe.com backend
Run with:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import database as db
from collectors import collect_all
from scorer import calculate_scores
import seed as seeder

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("jhfw")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 900))  # default 15 min


# ── Polling loop ────────────────────────────────────────────────────────────

async def polling_loop():
    """Background task: collect → score → persist, forever."""
    while True:
        try:
            log.info("⟳  Refreshing chaos data...")
            raw    = await collect_all()
            scored = calculate_scores(raw)
            await db.insert_snapshot(scored)
            if scored.get("signals"):
                await db.insert_signals(scored["signals"])
            log.info("✓  Overall chaos: %.1f — %s", scored["overall"], scored["label"])
        except Exception as exc:
            log.error("Polling cycle failed: %s", exc, exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await seeder.seed_if_empty()          # backfill 6 months on first run
    task = asyncio.create_task(polling_loop())
    log.info("Polling started — interval %ds", POLL_INTERVAL)
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Just How Fucked Are We — API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # lock down to your domain in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    n = await db.count_snapshots()
    return {"status": "ok", "snapshots": n, "ts": datetime.utcnow().isoformat()}


@app.get("/api/current")
async def current():
    data = await db.get_latest()
    if not data:
        raise HTTPException(503, "No data yet — seeding may be in progress")
    return JSONResponse(data)


@app.get("/api/history")
async def history(days: int = Query(default=180, ge=7, le=730)):
    rows = await db.get_history(days=days)
    return JSONResponse(rows)


class PollVote(BaseModel):
    score: int = Field(..., ge=1, le=10)


@app.post("/api/poll")
async def submit_poll(vote: PollVote, request: Request):
    ip_hash = None
    if request.client:
        import hashlib
        ip_hash = hashlib.sha256(request.client.host.encode()).hexdigest()[:16]
    await db.insert_poll_vote(vote.score, ip_hash)
    return {"status": "ok"}


@app.get("/api/poll")
async def poll_results():
    results = await db.get_poll_results()
    return JSONResponse(results)


@app.get("/api/au/scrapboard")
async def au_scrapboard():
    """Fetch live news for each AU chaos factor via Claude web search."""
    from collectors.au_scrapboard import fetch_all_factors
    try:
        results = await fetch_all_factors()
        return JSONResponse(results)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/au/scrapboard/{factor_id}")
async def au_scrapboard_factor(factor_id: str):
    """Fetch news for a single AU chaos factor."""
    from collectors.au_scrapboard import FACTORS, fetch_factor
    factor = next((f for f in FACTORS if f["id"] == factor_id), None)
    if not factor:
        raise HTTPException(404, f"Unknown factor: {factor_id}")
    try:
        result = await fetch_factor(factor)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/refresh")
async def force_refresh():
    """Manually trigger a data refresh (useful for testing)."""
    try:
        raw    = await collect_all()
        scored = calculate_scores(raw)
        await db.insert_snapshot(scored)
        if scored.get("signals"):
            await db.insert_signals(scored["signals"])
        return {"status": "refreshed", "overall": scored["overall"], "ts": scored["ts"]}
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
