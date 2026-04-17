"""
api_health/handler.py — GET /api/health
Returns API status and total snapshot count.
"""
import json
import logging
from datetime import datetime
import dynamo_db

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def lambda_handler(event, context):
    try:
        n = dynamo_db.count_snapshots()
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "status": "ok",
                "snapshots": n,
                "ts": datetime.utcnow().isoformat(),
            }),
        }
    except Exception as e:
        log.error("api/health failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
