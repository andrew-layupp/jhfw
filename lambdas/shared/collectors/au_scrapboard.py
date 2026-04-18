"""
AU Scrapboard — finds the latest articles & threads for each Australian
chaos factor.

Sources, in fallback order per factor:
1. Claude API with web search (when CLAUDE_API_KEY is set) — high-quality
   curated news articles per factor.
2. Google News RSS — reliable, no auth, used when Claude is unavailable.
3. Reddit r/Australia search — final fallback per factor.

The dedicated "reddit_australia" factor always pulls trending hot threads
straight from r/Australia.
"""
import os
import json
import logging
import asyncio
import html
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger(__name__)

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "").strip()
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5").strip()

REDDIT_BASE = "https://www.reddit.com"
REDDIT_SUBREDDIT = "australia"
REDDIT_USER_AGENT = "JHFW Scrapboard/1.0 (by github.com/andrew-layupp/jhfw)"

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

FACTORS = [
    {
        "id": "reddit_australia",
        "label": "r/Australia Trending",
        "reddit_only": True,
        "search_prompt": "",
    },
    {
        "id": "housing",
        "label": "Housing Crisis",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian housing crisis, property prices, mortgage stress, rental crisis, or housing affordability in Australia. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "housing OR mortgage OR rent OR property",
        "news_query": "Australia housing crisis OR mortgage stress OR rent",
    },
    {
        "id": "cost_of_living",
        "label": "Cost of Living",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian cost of living, inflation, grocery prices, electricity costs, insurance premiums, or RBA interest rate decisions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "\"cost of living\" OR inflation OR grocery OR \"electricity bill\" OR RBA",
        "news_query": "Australia cost of living OR inflation OR RBA interest rate",
    },
    {
        "id": "jobs",
        "label": "Jobs & Wages",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian unemployment, wages, underemployment, job losses, workplace changes, or labour market conditions. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "unemployment OR wages OR layoffs OR \"job market\"",
        "news_query": "Australia unemployment OR wages OR layoffs OR jobs",
    },
    {
        "id": "ai_jobs",
        "label": "AI Taking Jobs",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about AI replacing jobs in Australia, AI automation impact on Australian workers, tech layoffs in Australia, or AI disruption to Australian services economy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "AI OR automation OR ChatGPT OR \"tech layoff\"",
        "news_query": "Australia AI jobs OR automation OR tech layoffs",
    },
    {
        "id": "climate",
        "label": "Climate & Disasters",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian climate change impacts, bushfires, floods, coral bleaching, extreme weather events, or environmental policy in Australia. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "bushfire OR flood OR climate OR \"extreme weather\" OR drought",
        "news_query": "Australia bushfire OR flood OR climate OR drought",
    },
    {
        "id": "geopolitical",
        "label": "Geopolitical",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australia's geopolitical situation including China-Australia relations, AUKUS, Pacific influence, defence spending, trade tensions, or foreign policy. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "China OR AUKUS OR defence OR \"foreign policy\" OR Pacific",
        "news_query": "Australia China OR AUKUS OR defence OR Pacific",
    },
    {
        "id": "markets",
        "label": "Markets & Banks",
        "search_prompt": "Find the 5 most recent news articles (from the last 7 days) about Australian financial markets, ASX performance, Australian banking sector, AUD currency moves, iron ore prices, or superannuation. For each article, provide the headline, a 1-2 sentence summary, the source name, and the URL.",
        "reddit_keywords": "ASX OR bank OR AUD OR \"iron ore\" OR superannuation",
        "news_query": "Australia ASX OR bank OR AUD OR iron ore",
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


def _reddit_post_to_article(post: dict) -> dict:
    """Convert a Reddit post (the inner `data` dict) to an article dict."""
    title = html.unescape(post.get("title") or "")
    selftext = html.unescape(post.get("selftext") or "")
    summary = (selftext[:240] + "…") if len(selftext) > 240 else selftext
    if not summary:
        score = post.get("score") or 0
        comments = post.get("num_comments") or 0
        summary = f"{score} upvotes · {comments} comments on r/{post.get('subreddit', REDDIT_SUBREDDIT)}"
    permalink = post.get("permalink") or ""
    url = f"{REDDIT_BASE}{permalink}" if permalink else (post.get("url") or "")
    # Map Reddit score to 1-10 relevance: 100+ upvotes = 10, scaled log-ish.
    raw_score = post.get("score") or 0
    if raw_score >= 1000:
        relevance = 10
    elif raw_score >= 500:
        relevance = 9
    elif raw_score >= 200:
        relevance = 8
    elif raw_score >= 100:
        relevance = 7
    elif raw_score >= 50:
        relevance = 6
    elif raw_score >= 20:
        relevance = 5
    else:
        relevance = 4
    return {
        "headline": title or "(untitled post)",
        "summary": summary,
        "source": f"r/{post.get('subreddit', REDDIT_SUBREDDIT)}",
        "url": url,
        "relevance_score": relevance,
    }


async def _reddit_get(client: httpx.AsyncClient, path: str, params: dict) -> list:
    """Hit Reddit's public JSON API and return a list of post `data` dicts."""
    resp = await client.get(
        f"{REDDIT_BASE}{path}",
        params=params,
        headers={"User-Agent": REDDIT_USER_AGENT, "Accept": "application/json"},
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    children = (data.get("data") or {}).get("children") or []
    posts = []
    for child in children:
        d = child.get("data") or {}
        # Skip stickied/announcement posts and removed content
        if d.get("stickied") or d.get("removed_by_category"):
            continue
        posts.append(d)
    return posts


async def fetch_reddit_hot(limit: int = 10) -> list:
    """Fetch the current hot threads from r/Australia."""
    async with httpx.AsyncClient() as client:
        posts = await _reddit_get(
            client,
            f"/r/{REDDIT_SUBREDDIT}/hot.json",
            {"limit": limit + 5, "raw_json": 1},
        )
        return [_reddit_post_to_article(p) for p in posts[:limit]]


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _parse_news_source(title: str) -> tuple:
    """Google News titles look like 'Headline text - Publisher'. Split them."""
    if " - " in title:
        head, _, src = title.rpartition(" - ")
        return head.strip(), src.strip()
    return title.strip(), "Google News"


async def fetch_google_news(query: str, limit: int = 5) -> list:
    """Fetch articles from Google News RSS for an Australia-focused query."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_NEWS_RSS,
            params={"q": query, "hl": "en-AU", "gl": "AU", "ceid": "AU:en"},
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    items = root.findall(".//item")
    articles = []
    for item in items[:limit]:
        title_raw = (item.findtext("title") or "").strip()
        headline, source = _parse_news_source(html.unescape(title_raw))
        url = (item.findtext("link") or "").strip()
        desc = _strip_tags(html.unescape(item.findtext("description") or ""))
        # Description can include the publisher name as a trailing word — leave it.
        summary = (desc[:240] + "…") if len(desc) > 240 else desc
        # Recency-based relevance: anything within a day is high.
        relevance = 7
        pub = (item.findtext("pubDate") or "").strip()
        try:
            if pub:
                from datetime import datetime, timezone
                dt = parsedate_to_datetime(pub)
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                if age_h < 24:
                    relevance = 9
                elif age_h < 72:
                    relevance = 7
                else:
                    relevance = 5
        except Exception:
            pass
        articles.append({
            "headline": headline or "(untitled)",
            "summary": summary,
            "source": source,
            "url": url,
            "relevance_score": relevance,
        })
    return articles


async def fetch_reddit_search(query: str, limit: int = 5) -> list:
    """Search r/Australia for posts matching `query`, sorted by new."""
    async with httpx.AsyncClient() as client:
        posts = await _reddit_get(
            client,
            f"/r/{REDDIT_SUBREDDIT}/search.json",
            {
                "q": query,
                "restrict_sr": 1,
                "sort": "new",
                "t": "week",
                "limit": limit,
                "raw_json": 1,
            },
        )
        return [_reddit_post_to_article(p) for p in posts[:limit]]


async def _fetch_factor_via_claude(factor: dict) -> list:
    """Call Claude web search and return parsed articles. Raises on failure."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
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

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        text = text.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON array in Claude response")
        return json.loads(text[start : end + 1])


async def fetch_factor(factor: dict) -> dict:
    """Fetch articles for one factor. Falls back to Reddit if Claude is unavailable."""
    factor_id = factor["id"]
    label = factor["label"]

    # Reddit-only factor: always use Reddit hot listing.
    if factor.get("reddit_only"):
        try:
            articles = await fetch_reddit_hot(limit=10)
            log.info("Scrapboard [%s]: %d Reddit hot posts", factor_id, len(articles))
            return {"id": factor_id, "label": label, "articles": articles}
        except Exception as e:
            log.error("Scrapboard [%s] reddit fetch failed: %s", factor_id, e)
            return {"id": factor_id, "label": label, "articles": [], "error": f"Reddit fetch failed: {e}"}

    claude_error = None
    if CLAUDE_API_KEY:
        try:
            articles = await _fetch_factor_via_claude(factor)
            if articles:
                log.info("Scrapboard [%s]: %d articles via Claude", factor_id, len(articles))
                return {"id": factor_id, "label": label, "articles": articles}
            claude_error = "Claude returned 0 articles"
        except Exception as e:
            claude_error = f"Claude search failed: {e}"
            log.warning("Scrapboard [%s] %s", factor_id, claude_error)
    else:
        claude_error = "No CLAUDE_API_KEY set"

    # Fallback 1: Google News RSS for this factor's query (most reliable).
    news_query = factor.get("news_query")
    if news_query:
        try:
            articles = await fetch_google_news(news_query, limit=5)
            if articles:
                log.info("Scrapboard [%s]: %d articles via Google News", factor_id, len(articles))
                return {
                    "id": factor_id,
                    "label": label,
                    "articles": articles,
                    "error": f"{claude_error} — showing Google News results",
                }
        except Exception as e:
            log.warning("Scrapboard [%s] google news fallback failed: %s", factor_id, e)
            claude_error = f"{claude_error}; google news failed: {e}"

    # Fallback 2: Reddit search for this factor's keywords.
    keywords = factor.get("reddit_keywords")
    if keywords:
        try:
            articles = await fetch_reddit_search(keywords, limit=5)
            if articles:
                log.info("Scrapboard [%s]: %d articles via Reddit fallback", factor_id, len(articles))
                return {
                    "id": factor_id,
                    "label": label,
                    "articles": articles,
                    "error": f"{claude_error} — showing r/Australia results",
                }
        except Exception as e:
            log.error("Scrapboard [%s] reddit fallback failed: %s", factor_id, e)
            claude_error = f"{claude_error}; reddit fallback failed: {e}"

    return {"id": factor_id, "label": label, "articles": [], "error": claude_error}


async def fetch_all_factors() -> list:
    """Fetch articles for all factors. Runs in parallel for speed."""
    tasks = [fetch_factor(factor) for factor in FACTORS]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
