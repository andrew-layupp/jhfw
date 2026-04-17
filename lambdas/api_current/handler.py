"""
api_current/handler.py — GET /api/current
Returns the latest chaos snapshot + live signals from DynamoDB.
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
        data = dynamo_db.get_latest()
        if not data:
            return {
                "statusCode": 503,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "No data yet — seeding may be in progress"}),
            }
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(data),
        }
    except Exception as e:
        log.error("api/current failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
