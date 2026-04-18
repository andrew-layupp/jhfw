"""
us_scrapboard/handler.py

Three handlers:
- lambda_handler: on-demand fetch (GET /api/us/scrapboard, /api/us/scrapboard/{factor_id})
- cache_handler: scheduled every 6h — runs Claude web search, stores in DynamoDB
- read_handler: GET /api/us/news — reads cached results from DynamoDB (instant)
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from decimal import Decimal

import boto3

from collectors.us_scrapboard import fetch_all_factors, fetch_factor, FACTORS

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

US_SCRAPBOARD_TABLE = os.getenv("US_SCRAPBOARD_TABLE", "jhfw-us-scrapboard")

_dynamodb = None
def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(US_SCRAPBOARD_TABLE)


# ── On-demand handler ──────────────────────────────────────────────

def lambda_handler(event, context):
    try:
        path = event.get("rawPath", "") or event.get("path", "")
        path_params = event.get("pathParameters") or {}
        factor_id = path_params.get("factor_id")

        if not factor_id and "/scrapboard/" in path:
            factor_id = path.split("/scrapboard/")[-1].strip("/")

        if factor_id:
            factor = next((f for f in FACTORS if f["id"] == factor_id), None)
            if not factor:
                return {"statusCode": 404, "headers": CORS_HEADERS, "body": json.dumps({"error": f"Unknown factor: {factor_id}"})}
            result = asyncio.run(fetch_factor(factor))
            return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(result)}

        results = asyncio.run(fetch_all_factors())
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(results)}
    except Exception as e:
        log.error("US scrapboard failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}


# ── Scheduled cache handler (every 6h) ────────────────────────────

def cache_handler(event, context):
    """Runs Claude web search for all US factors and caches results in DynamoDB."""
    try:
        log.info("Starting scheduled US scrapboard cache refresh...")
        results = asyncio.run(fetch_all_factors())
        table = _get_table()
        ts = datetime.utcnow().isoformat()

        for factor in results:
            articles = factor.get("articles", [])
            clean_articles = []
            for a in articles:
                item = {k: v for k, v in a.items() if v is not None}
                if "relevance_score" in item:
                    item["relevance_score"] = Decimal(str(item["relevance_score"]))
                clean_articles.append(item)

            item = {
                "factor_id": factor["id"],
                "label": factor["label"],
                "articles": clean_articles,
                "updated_at": ts,
                "error": factor.get("error", ""),
            }
            if factor.get("severity_score") is not None:
                item["severity_score"] = Decimal(str(factor["severity_score"]))
            if factor.get("severity_summary"):
                item["severity_summary"] = factor["severity_summary"]
            table.put_item(Item=item)
            log.info("Cached US %s: %d articles, severity=%s", factor["id"], len(articles), factor.get("severity_score"))

        log.info("US scrapboard cache refresh complete — %d factors", len(results))
        return {"statusCode": 200, "body": json.dumps({"cached": len(results), "ts": ts})}
    except Exception as e:
        log.error("US cache refresh failed: %s", e, exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


# ── Read cached results (instant) ─────────────────────────────────

def read_handler(event, context):
    """Read cached US scrapboard results from DynamoDB. Instant response."""
    try:
        table = _get_table()
        resp = table.scan()
        items = resp.get("Items", [])

        results = []
        for item in items:
            articles = item.get("articles", [])
            clean = []
            for a in articles:
                ca = dict(a)
                if "relevance_score" in ca:
                    ca["relevance_score"] = float(ca["relevance_score"])
                clean.append(ca)
            entry = {
                "id": item["factor_id"],
                "label": item.get("label", ""),
                "articles": clean,
                "updated_at": item.get("updated_at", ""),
            }
            if "severity_score" in item:
                entry["severity_score"] = float(item["severity_score"])
            if "severity_summary" in item:
                entry["severity_summary"] = item["severity_summary"]
            results.append(entry)

        order = {f["id"]: i for i, f in enumerate(FACTORS)}
        results.sort(key=lambda x: order.get(x["id"], 99))

        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(results)}
    except Exception as e:
        log.error("Read cached US scrapboard failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}
