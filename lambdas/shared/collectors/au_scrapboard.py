"""
AU Scrapboard — uses Claude API with web search to find the latest
news articles for each Australian chaos factor.
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
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian housing crisis, property prices, mortgage stress, rental crisis, or housing affordability in Australia. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "cost_of_living",
        "label": "Cost of Living",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian cost of living, inflation, grocery prices, electricity costs, insurance premiums, or RBA interest rate decisions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "jobs",
        "label": "Jobs & Wages",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian unemployment, wages, underemployment, job losses, workplace changes, or labour market conditions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "ai_jobs",
        "label": "AI Taking Jobs",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about AI replacing jobs in Australia, AI automation impact on Australian workers, tech layoffs in Australia, or AI disruption to Australian services economy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "climate",
        "label": "Climate & Disasters",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian climate change impacts, bushfires, floods, coral bleaching, extreme weather events, or environmental policy in Australia. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "geopolitical",
        "label": "Geopolitical",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australia's geopolitical situation including China-Australia relations, AUKUS, Pacific influence, defence spending, trade tensions, or foreign policy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
    {
        "id": "markets",
        "label": "Markets & Banks",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian financial markets, ASX performance, Australian banking sector, AUD currency moves, iron ore prices, or superannuation. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
    },
]

RESPONSE_FORMAT = """
Return your response as a JSON array. Each item must have these fields:
- "headline": string (the article headline)
- "summary": string (1-2 sentence summary)
- "source": string (publication name e.g. "ABC News", "SMH", "AFR")
- "url": string (the full URL to the article)
- "relevance_score": number (1-10 how relevant this is to measuring how fucked Australia is)

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

            # Parse JSON from response — handle markdown fences and mixed content
            text = text.strip()
            # Find JSON array in the response
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                text = text[start:end + 1]
            articles = json.loads(text)

            log.info("Scrapboard [%s]: found %d articles", factor["id"], len(articles))
            return {
                "id": factor["id"],
                "label": factor["label"],
                "articles": articles,
            }
    except Exception as e:
        log.error("Scrapboard [%s] failed: %s", factor["id"], e)
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
