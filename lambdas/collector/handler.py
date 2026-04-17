"""
collector/handler.py — EventBridge-triggered every 15 minutes.
Collects all data sources, calculates scores, persists to DynamoDB.
Identical logic to the polling_loop() in backend/main.py.
"""
import asyncio
import json
import logging
import dynamo_db
from collectors import collect_all
from scorer import calculate_scores

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def lambda_handler(event, context):
    try:
        log.info("Starting chaos data collection...")
        raw    = asyncio.run(collect_all())
        scored = calculate_scores(raw)
        dynamo_db.insert_snapshot(scored)
        if scored.get("signals"):
            dynamo_db.insert_signals(scored["signals"])
        log.info("Overall chaos: %.1f — %s", scored["overall"], scored["label"])
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "status":  "ok",
                "overall": scored["overall"],
                "label":   scored["label"],
                "ts":      scored["ts"],
            }),
        }
    except Exception as e:
        log.error("Collector failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
