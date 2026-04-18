"""
poll/handler.py — GET /api/poll and POST /api/poll
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


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "POST":
        return _submit_vote(event)
    else:
        return _get_results()


def _submit_vote(event):
    try:
        body = json.loads(event.get("body", "{}"))
        score = body.get("score")
        if not score or not isinstance(score, int) or score < 1 or score > 10:
            return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "score must be 1-10"})}

        # Hash IP for dedup
        ip = event.get("requestContext", {}).get("http", {}).get("sourceIp", "unknown")
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

        ts = datetime.utcnow().isoformat()
        table = _get_table()
        table.put_item(Item={
            "vote_id": f"{ip_hash}_{ts}",
            "ts": ts,
            "score": score,
            "ip_hash": ip_hash,
        })

        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps({"status": "ok"})}
    except Exception as e:
        log.error("Poll submit failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}


def _get_results():
    try:
        table = _get_table()
        # Scan all votes
        items = []
        kwargs = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last

        distribution = {str(i): 0 for i in range(1, 11)}
        total = 0
        weighted_sum = 0
        for item in items:
            s = int(item.get("score", 0))
            if 1 <= s <= 10:
                distribution[str(s)] += 1
                total += 1
                weighted_sum += s

        average = round(weighted_sum / total, 2) if total > 0 else 0.0

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({"total_votes": total, "average": average, "distribution": distribution}),
        }
    except Exception as e:
        log.error("Poll results failed: %s", e, exc_info=True)
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps({"error": str(e)})}
