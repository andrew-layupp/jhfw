"""
api_history/handler.py — GET /api/history?days=180
Returns one snapshot per day for the past N days (7 ≤ days ≤ 730).
"""
import json
import logging
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
        params = event.get("queryStringParameters") or {}
        try:
            days = int(params.get("days", 180))
        except (ValueError, TypeError):
            days = 180
        days = max(7, min(730, days))  # clamp to valid range

        rows = dynamo_db.get_history(days=days)
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(rows),
        }
    except Exception as e:
        log.error("api/history failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
