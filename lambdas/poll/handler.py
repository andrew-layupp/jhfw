"""
poll/handler.py — GET /api/poll, GET /api/poll/recent, and POST /api/poll
Stores and retrieves community poll votes from DynamoDB.
"""
import json
import hashlib
import logging
import os
from datetime import datetime
from decimal import Decimal

import boto3

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

POLL_TABLE = os.getenv("POLL_TABLE", "jhfw-poll")
_dynamodb = None

def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(POLL_TABLE)


def _get_country(event, from_body=False):
    """Extract country code from query params or body. Defaults to 'au'."""
    if from_body:
        body = json.loads(event.get("body", "{}"))
        country = body.get("country", "").lower().strip()
        if country in ("au", "us"):
            return country
    qs = event.get("queryStringParameters") or {}
    country = (qs.get("country") or "au").lower().strip()
    return country if country in ("au", "us") else "au"


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "") or event.get("path", "")

    if method == "POST":
        return _submit_vote(event)
    elif "/recent" in path:
        return _get_recent(event)
    else:
        return _get_results(event)


def _submit_vote(event):
    try:
        body = json.loads(event.get("body", "{}"))
        score = body.get("score")
        if not score or not isinstance(score, int) or score not in (1,2,3,4,5,6,7,8,9,10,20,40,60,80,100):
            return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "invalid score"})}

        country = _get_country(event, from_body=True)

        # Hash IP for dedup
        ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

        ts = datetime.utcnow().isoformat()
        item = {
            "vote_id": f"{ip_hash}_{ts}",
            "ts": ts,
            "score": score,
            "ip_hash": ip_hash,
            "country": country,
        }

        # Optional factor selections and reason
        factors = body.get("factors")
        if factors and isinstance(factors, list):
            item["factors"] = factors[:7]
        reason = body.get("reason")
        if reason and isinstance(reason, str):
            item["reason"] = reason[:140]
        # metadata_only votes are stored for the ticker but not counted in poll results
        if body.get("metadata_only"):
            item["metadata_only"] = True

        table = _get_table()
        table.put_item(Item=item)

        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps({"status": "ok"})}
    except Exception as e:
        log.error("Poll submit failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}


def _get_results(event):
    try:
        country = _get_country(event)
        table = _get_table()
        items = []
        kwargs = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        # Count votes filtered by country
        # Votes without a country field are treated as 'au' (legacy)
        # Skip metadata_only votes (factor follow-ups stored for ticker only)
        distribution = {}
        total = 0
        for item in items:
            if item.get("metadata_only"):
                continue
            item_country = item.get("country", "au")
            if item_country != country:
                continue
            s = int(item.get("score", 0))
            if s > 0:
                distribution[str(s)] = distribution.get(str(s), 0) + 1
                total += 1

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({"total_votes": total, "distribution": distribution}),
        }
    except Exception as e:
        log.error("Poll results failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}


def _get_recent(event):
    """Return recent votes that include factor selections, for the live ticker."""
    try:
        country = _get_country(event)
        table = _get_table()
        items = []
        kwargs = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        # Filter to votes with factors, for this country, sort by ts desc
        filtered = [i for i in items
                    if i.get("country", "au") == country and i.get("factors")]
        filtered.sort(key=lambda x: x.get("ts", ""), reverse=True)
        recent = filtered[:20]

        result = [{"ts": i["ts"], "score": int(i["score"]),
                   "factors": list(i.get("factors", [])),
                   "reason": i.get("reason"),
                   "country": i.get("country", "au")}
                  for i in recent]

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(result, default=str),
        }
    except Exception as e:
        log.error("Recent votes failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}
