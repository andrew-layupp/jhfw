# JHFW — Just How Fucked Are We?

A real-time chaos index that gives you one number for how fucked things are — then lets you dig into exactly why.

## What is this?

JHFW starts with a simple question: **how fucked are we?**

It answers with a single score out of 100, updated every 15 minutes, pulling live data from financial markets, government statistics, climate sensors, and news feeds.

But the score is just the headline. The real value is in the layers underneath.

## How it works

### Layer 1: The Score
One number. At a glance, you know if things are fine, tense, not great, fucked, or cooked. The score is calculated from weighted dimensions — each one pulling from real, verifiable data sources.

### Layer 2: The Dimensions
Drill into the six factors that make up the score. Each dimension has its own score, data sources, and explanation of what's driving it:

**For Australia:**
- **Housing & Debt (25%)** — $2.5T mortgage debt, median prices, vacancy rates, debt-to-income ratios
- **Cost of Living (20%)** — CPI, RBA cash rate, energy prices, insurance
- **Jobs & AI Risk (20%)** — Unemployment, services economy exposure (80%), AI displacement of knowledge workers (39% of workforce)
- **Climate & Disasters (15%)** — Temperature anomaly, bleaching events, bushfire risk, energy policy
- **Geopolitical (10%)** — China relations, AUKUS, Pacific influence
- **Markets & Banks (10%)** — ASX, AUD, iron ore, bank dominance (4 of 6 biggest ASX companies are banks)

### Layer 3: The Research
This is where JHFW goes deeper than any dashboard. The **AU Scrapboard** uses Claude with web search to find the latest news articles for each chaos factor — in real time. Every article is clickable, sourced, and scored for relevance.

Not headlines we picked. Headlines Claude found right now, for each factor, with links to the original reporting.

## Why Australia first?

Because Australia is a fascinating case study in systemic risk:
- **80% services economy** — the exact jobs AI is best at replacing
- **Highest household debt-to-income ratio in the Western world**
- **$2.5 trillion in mortgage debt** — one country betting on one asset class with borrowed money
- **4 of the 6 biggest companies are banks** — the economy is built around servicing property
- **Energy stuck in no man's land** — committed to net zero but blocking nuclear, shutting coal, not building fast enough

If the knowledge workers lose their jobs, they can't service their mortgages. If they can't service their mortgages, the tenants don't have landlords. The whole Jenga tower depends on everyone keeping their job.

## Data sources

All data is live and verifiable:
- **Markets:** Yahoo Finance (VIX, S&P 500, ASX, Gold, Oil, Bitcoin, AUD/USD, Treasury yields)
- **Economics:** FRED (US CPI, Fed rate, unemployment, jobless claims, Case-Shiller, median home prices)
- **Climate:** Open-Meteo (global temperature anomaly vs 1991-2000 baseline across 8 cities)
- **News:** GDELT (conflict and trade article volumes with 90-day baselines), NewsAPI fallback
- **Research:** Claude API with web search (real-time article discovery for each factor)

## Architecture

- **Frontend:** Static HTML on AWS Amplify (auto-deploys from GitHub)
- **Backend:** AWS Lambda + API Gateway + DynamoDB
- **Data collection:** EventBridge triggers Lambda every 15 minutes
- **Research:** Claude API with web search tool for scrapboard
- **Cost:** ~$0-3/month on AWS free tier

## What's next

- Make AU dimensions live (not hardcoded) with AU-specific data collectors
- Add scoring methodology transparency (show exactly how each dimension is calculated)
- Community features — let people contribute evidence for each factor
- Historical tracking — see how each dimension has changed over time
- Alerts — get notified when a dimension spikes
