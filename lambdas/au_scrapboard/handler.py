"""
au_scrapboard/handler.py — GET /api/au/scrapboard
Uses Claude API with web search to find latest news for each AU chaos factor.
"""
import asyncio
import json
import logging
from collectors.au_scrapboard import fetch_all_factors, fetch_factor, FACTORS

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
        # Check if a specific factor was requested
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
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(results),
        }
    except Exception as e:
        log.error("AU scrapboard failed: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
