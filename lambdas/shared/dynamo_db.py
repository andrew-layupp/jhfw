"""
dynamo_db.py — DynamoDB data layer replacing SQLite database.py.

Tables (created by CloudFormation/SAM):
  jhfw-snapshots  PK: ts (S)           — chaos snapshots
  jhfw-signals    PK: ts (S), SK: text (S) — signal feed

Uses a 'LATEST' sentinel item in the snapshots table so get_latest()
is a single GetItem call rather than a full-table scan.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr

log = logging.getLogger(__name__)

SNAPSHOTS_TABLE = os.getenv("SNAPSHOTS_TABLE") or f"{os.getenv('TABLE_PREFIX', 'jhfw')}-snapshots"
SIGNALS_TABLE   = os.getenv("SIGNALS_TABLE")   or f"{os.getenv('TABLE_PREFIX', 'jhfw')}-signals"

_dynamodb = None


def _resource():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _snapshots():
    return _resource().Table(SNAPSHOTS_TABLE)


def _signals():
    return _resource().Table(SIGNALS_TABLE)


# ── Decimal helpers ──────────────────────────────────────────────────────────

def _dec(v) -> Optional[Decimal]:
    """Convert a numeric value to Decimal for DynamoDB storage."""
    if v is None:
        return None
    return Decimal(str(v))


def _from_decimal(obj):
    """Recursively convert Decimal → float for JSON serialisation."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(v) for v in obj]
    return obj


# ── Public API ───────────────────────────────────────────────────────────────

def init_tables():
    """Validate tables exist. Creation is handled by CloudFormation/SAM."""
    for tbl in [_snapshots(), _signals()]:
        try:
            tbl.load()
            log.info("Table %s is ready.", tbl.name)
        except Exception as e:
            log.warning("Table %s may not be ready: %s", tbl.name, e)


def insert_snapshot(data: dict):
    """
    Put a chaos snapshot into DynamoDB.
    Also overwrites a 'LATEST' sentinel item for O(1) get_latest() lookups.
    """
    ts     = data.get("ts") or datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    scores = data.get("scores", {})
    raw    = data.get("raw", {})

    def _build_item(ts_val: str) -> dict:
        item = {
            "ts":       ts_val,
            "raw_json": json.dumps(raw),
        }
        for key, val in [
            ("overall", data.get("overall")),
            ("geo",     scores.get("geo")),
            ("markets", scores.get("markets")),
            ("energy",  scores.get("energy")),
            ("trade",   scores.get("trade")),
            ("climate", scores.get("climate")),
            ("living",  scores.get("living")),
            ("vix",     raw.get("vix")),
            ("oil",     raw.get("oil")),
            ("gold",    raw.get("gold")),
            ("spy",     raw.get("spy")),
            ("audusd",  raw.get("audusd")),
        ]:
            d = _dec(val)
            if d is not None:
                item[key] = d
        return item

    tbl = _snapshots()
    tbl.put_item(Item=_build_item(ts))
    tbl.put_item(Item=_build_item("LATEST"))
    log.info("Inserted snapshot ts=%s overall=%s", ts, data.get("overall"))


def insert_signals(signals: list):
    """Batch-write signal rows. Deduplication is by (ts, text) composite key."""
    if not signals:
        return
    ts  = datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    tbl = _signals()
    # batch_writer automatically chunks into groups of 25 (DynamoDB limit)
    with tbl.batch_writer() as batch:
        for s in signals:
            text = (s.get("text") or "")[:1024]
            if not text:
                continue
            item = {"ts": ts, "text": text}
            if s.get("category"):
                item["category"] = s["category"]
            if s.get("source"):
                item["source"] = s["source"]
            if s.get("url"):
                item["url"] = s["url"]
            batch.put_item(Item=item)


def get_latest() -> Optional[dict]:
    """Return the latest snapshot + recent signals using the LATEST sentinel."""
    resp = _snapshots().get_item(Key={"ts": "LATEST"})
    item = resp.get("Item")
    if not item:
        return None

    # Recent signals — scan all, sort by ts desc, deduplicate by text prefix
    sig_items = _scan_all(_signals())
    sig_items.sort(key=lambda x: x.get("ts", ""), reverse=True)
    import re
    seen = set()
    sigs = []
    for s in sig_items:
        # Deduplicate: strip numbers/punctuation so "Gold up 45.4%" and "Gold up 45.5%" match
        key = re.sub(r'[\d,.$%+\-]+', '', s.get("text", ""))[:40]
        if key in seen:
            continue
        seen.add(key)
        sigs.append({
            "text":     s.get("text", ""),
            "category": s.get("category"),
            "source":   s.get("source"),
            "url":      s.get("url"),
            "ts":       s.get("ts", ""),
        })
        if len(sigs) >= 12:
            break

    return _item_to_dict(item, sigs)


def get_history(days: int = 180) -> list:
    """Return one snapshot per day (latest of that day) for the past N days."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    # Scan with filter — exclude the LATEST sentinel
    # Note: "LATEST" > any ISO timestamp string lexicographically (L > 2),
    # so we must explicitly exclude it even though the gte filter should be
    # checked: 'L'(76) > '2'(50) in ASCII, so LATEST passes gte filter.
    items = _scan_all(
        _snapshots(),
        FilterExpression=Attr("ts").gte(since) & Attr("ts").ne("LATEST"),
    )

    # Sort ascending by ts
    items.sort(key=lambda x: x.get("ts", ""))

    # Group by day — keep last entry per day (already sorted ascending)
    by_day: dict = {}
    for item in items:
        day = item["ts"][:10]
        by_day[day] = item

    return [_item_to_dict(v) for v in sorted(by_day.values(), key=lambda x: x["ts"])]


def count_snapshots() -> int:
    """Return total snapshot count, excluding the LATEST sentinel item."""
    total = 0
    tbl   = _snapshots()
    kwargs: dict = {
        "Select": "COUNT",
        "FilterExpression": Attr("ts").ne("LATEST"),
    }
    while True:
        resp   = tbl.scan(**kwargs)
        total += resp.get("Count", 0)
        last   = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return total


# ── Internal helpers ─────────────────────────────────────────────────────────

def _scan_all(table, **kwargs) -> list:
    """Paginate through all items in a DynamoDB table scan."""
    items = []
    while True:
        resp   = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last   = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def _item_to_dict(item: dict, signals=None) -> dict:
    """Convert a DynamoDB item to the standard API response shape."""
    item = _from_decimal(dict(item))  # copy + convert all Decimals → float
    scores = {
        "geo":     item.pop("geo",     None),
        "markets": item.pop("markets", None),
        "energy":  item.pop("energy",  None),
        "trade":   item.pop("trade",   None),
        "climate": item.pop("climate", None),
        "living":  item.pop("living",  None),
    }
    raw_str = item.pop("raw_json", None)
    raw     = json.loads(raw_str) if raw_str else {}
    # Remove individual raw columns — canonical values live in raw_json
    for k in ("vix", "oil", "gold", "spy", "audusd"):
        item.pop(k, None)

    result = {**item, "scores": scores, "raw": raw}
    if signals is not None:
        result["signals"] = signals
    return result
