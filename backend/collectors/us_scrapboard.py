"""
US Scrapboard — uses Claude API with web search to find the latest
news articles for each American chaos factor.
"""
import os
import json
import logging
import httpx

log = logging.getLogger(__name__)

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "").strip()
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

FACTORS = [
    {
        "id": "housing",
        "label": "Housing Crisis",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about the US housing crisis, home prices, mortgage rates, rent crisis, or housing affordability in America. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "cost_of_living",
        "label": "Cost of Living",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about American cost of living, gas prices, inflation, grocery prices, energy costs, insurance premiums, or Federal Reserve interest rate decisions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "healthcare",
        "label": "Healthcare",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about US healthcare costs, medical debt, health insurance, prescription drug prices, Medicare/Medicaid, or the uninsured crisis in America. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "jobs",
        "label": "Jobs & AI",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about US unemployment, wages, tech layoffs, AI replacing American jobs, AI automation impact on US workers, or labor market conditions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "national_debt",
        "label": "National Debt",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about US national debt, federal deficit, debt ceiling, government spending, Treasury yields, or fiscal policy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "geopolitical",
        "label": "Geopolitical",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about US geopolitical situation including China-US relations, NATO, tariffs, trade wars, defense spending, sanctions, or foreign policy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "markets",
        "label": "Markets & Economy",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about US financial markets, S&P 500, NASDAQ, Dow Jones, Wall Street, banking sector, or Federal Reserve policy impact on markets. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
]

RESPONSE_FORMAT = """
Return your response as a JSON object with these fields:
- "severity_score": number (0-100, how bad is this factor RIGHT NOW for America? 0=totally fine, 50=concerning, 75=pretty fucked, 100=completely fucked. Be honest and data-driven.)
- "severity_summary": string (one sentence explaining why you gave this score)
- "articles": array of objects, each with:
  - "headline": string (the article headline)
  - "summary": string (1-2 sentence summary of the article)
  - "source": string (publication name e.g. "CNN", "NYT", "WSJ")
  - "url": string (the full URL to the article)
  - "relevance_score": number (1-10 how relevant this article is)

Base your severity_score on the ACTUAL data and news you find, not assumptions. If things are genuinely fine, score low. If things are genuinely bad, score high.

Return ONLY valid JSON, no markdown, no code fences, no explanation.
"""


async def fetch_factor(factor: dict) -> dict:
    """Use Claude with web search to find articles for one factor."""
    if not CLAUDE_API_KEY:
        log.warning("CLAUDE_API_KEY not set — skipping scrapboard")
        return {"id": factor["id"], "label": factor["label"], "articles": [], "error": "No API key"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 2048,
                    "tools": [
                        {
                            "type": "web_search_20250305",
                            "name": "web_search",
                            "max_uses": 10,
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": factor["search_prompt"] + "\n\n" + RESPONSE_FORMAT,
                        }
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract text content from Claude's response
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")

            # Parse JSON from response
            text = text.strip()
            obj_start = text.find("{")
            arr_start = text.find("[")

            parsed = None
            if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
                end = text.rfind("}")
                if end != -1:
                    parsed = json.loads(text[obj_start:end + 1])
            elif arr_start != -1:
                end = text.rfind("]")
                if end != -1:
                    parsed = json.loads(text[arr_start:end + 1])

            if isinstance(parsed, dict):
                articles = parsed.get("articles", [])
                severity = parsed.get("severity_score")
                severity_summary = parsed.get("severity_summary", "")
            elif isinstance(parsed, list):
                articles = parsed
                severity = None
                severity_summary = ""
            else:
                articles = []
                severity = None
                severity_summary = ""

            log.info("US Scrapboard [%s]: %d articles, severity=%s", factor["id"], len(articles), severity)
            result = {
                "id": factor["id"],
                "label": factor["label"],
                "articles": articles,
            }
            if severity is not None:
                result["severity_score"] = severity
            if severity_summary:
                result["severity_summary"] = severity_summary
            return result
    except Exception as e:
        log.error("US Scrapboard [%s] failed: %s", factor["id"], e)
        return {
            "id": factor["id"],
            "label": factor["label"],
            "articles": [],
            "error": str(e),
        }


async def fetch_all_factors() -> list:
    """Fetch articles for all factors. Runs in parallel for speed."""
    import asyncio
    tasks = [fetch_factor(factor) for factor in FACTORS]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
