# justhowfuckedarewe.com — Global Chaos Index

A live dashboard tracking global chaos across 6 dimensions using freely available data APIs — no paid subscriptions required.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   AWS Amplify (Frontend)                 │
│  frontend/index.html  ──  static HTML/JS/CSS            │
│  amplify.yml          ──  build: injects BACKEND_URL    │
└────────────────────────┬────────────────────────────────┘
                         │ fetch /api/*
┌────────────────────────▼────────────────────────────────┐
│              API Gateway HTTP API (CORS: *)              │
│  GET /api/current   GET /api/history   GET /api/health  │
└──────┬──────────────────┬──────────────────┬────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼──────┐  ┌───────▼──────┐
│  api_current│  │  api_history  │  │  api_health  │
│  Lambda     │  │  Lambda       │  │  Lambda      │
└──────┬──────┘  └────────┬──────┘  └───────┬──────┘
       │                  │                  │
┌──────▼──────────────────▼──────────────────▼──────────┐
│          DynamoDB (on-demand billing)                   │
│  jhfw-snapshots  PK: ts (S)                            │
│  jhfw-signals    PK: ts (S)  SK: text (S)              │
└──────────────────────────────────────────────────────┬─┘
                                                       │
┌──────────────────────────────────────────────────────▼─┐
│  collector Lambda  ──  EventBridge: rate(15 minutes)   │
│  seeder Lambda     ──  manually invoked (first run)    │
│                                                         │
│  Both use shared Lambda layers:                         │
│    SharedCodeLayer:  dynamo_db.py, scorer.py,           │
│                      collectors/ (markets/news/climate) │
│    DependencyLayer:  yfinance, pandas, httpx            │
└─────────────────────────────────────────────────────────┘

Local dev (unchanged):
  backend/  ──  FastAPI + SQLite (uvicorn main:app)
```

## Data sources (all free, no API key)

| Dimension | Source | Signal |
|---|---|---|
| Markets | yfinance (Yahoo Finance) | VIX, S&P 500 drawdown, Gold 1Y change |
| Energy | yfinance | Brent crude price + 30-day change |
| Geopolitical | GDELT Project | Conflict article volume vs 90-day baseline |
| Trade Wars | GDELT Project | Tariff/sanctions article volume vs baseline |
| Climate | Open-Meteo archive API | Temp anomaly vs 1991–2020 baseline (8 cities) |
| Cost of Living | Cached (monthly update) | AU CPI + RBA cash rate |

## Scoring

Each dimension is normalised to **0–100**. The overall score is a weighted composite:

| Dimension | Weight |
|---|---|
| Geopolitical | 25% |
| Energy | 20% |
| Trade Wars | 20% |
| Markets | 15% |
| Climate | 10% |
| Cost of Living | 10% |

Labels: Fine (0–20) · Tense (21–40) · Not great (41–60) · Fucked (61–75) · Severely fucked (76–88) · Completely cooked (89–100)

---

## Local development (existing backend — unchanged)

The original FastAPI + SQLite backend still works exactly as before.

### Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Run the backend

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On first run the backend will:
1. Initialise a local `chaos.db` SQLite database
2. Backfill 6 months of history from yfinance (~60 s)
3. Start polling all data sources every 15 minutes

### Open the frontend

Open `frontend/index.html` directly in your browser. It connects to `http://localhost:8000` by default.

To point it at a remote backend:
```html
<script>window.JHFW_BACKEND = 'https://your-api.execute-api.ap-southeast-2.amazonaws.com';</script>
```

### Local API endpoints

```
GET /api/health     — health check + snapshot count
GET /api/current    — latest chaos scores + signals
GET /api/history    — daily snapshots for past N days (?days=180)
GET /api/refresh    — force an immediate data refresh
```

---

## AWS Serverless deployment (SAM + Lambda + DynamoDB)

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| AWS CLI | ≥ 2.x | https://aws.amazon.com/cli/ |
| SAM CLI | ≥ 1.100 | https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html |
| Python | 3.12 | https://python.org |
| Docker | any | Required by SAM build for Lambda layers |

Configure AWS credentials before deploying:
```bash
aws configure
# or: export AWS_PROFILE=your-profile
```

### First-time deploy

```bash
chmod +x deploy.sh
./deploy.sh --guided
```

The guided deploy will prompt for:
- Stack name (default: `jhfw-serverless`)
- AWS region (e.g. `ap-southeast-2` for Sydney)
- S3 bucket for SAM artifacts (SAM creates it)
- Whether to save settings to `samconfig.toml`

Subsequent deploys:
```bash
./deploy.sh
```

### Seed historical data

After the first deploy, backfill 6 months of weekly snapshots:

```bash
aws lambda invoke \
  --function-name jhfw-seeder \
  --region ap-southeast-2 \
  --log-type Tail \
  /tmp/seed-output.json \
&& cat /tmp/seed-output.json
```

The seeder skips automatically if ≥ 10 snapshots already exist.

### Connect the frontend (AWS Amplify)

1. Push this repo to GitHub/GitLab/Bitbucket
2. Open the [Amplify Console](https://console.aws.amazon.com/amplify/)
3. **New app → Host web app** → connect your repository
4. Amplify auto-detects `amplify.yml`
5. In **Environment variables**, add:
   ```
   BACKEND_URL = https://<api-id>.execute-api.<region>.amazonaws.com
   ```
   (Printed by `deploy.sh` after a successful deploy.)
6. Trigger a build — Amplify injects the URL and deploys the static site.

### Serverless file layout

```
template.yaml               AWS SAM template (API GW + Lambdas + DynamoDB)
amplify.yml                 Amplify build config (injects BACKEND_URL)
deploy.sh                   One-command deploy script
requirements-lambda.txt     Lambda layer deps (yfinance, pandas, httpx)

lambdas/
  shared/                   Shared Python code (packaged as Lambda layer)
    dynamo_db.py            DynamoDB wrapper (replaces backend/database.py)
    scorer.py               Scoring logic (identical to backend/scorer.py)
    collectors/             Data collectors (identical to backend/collectors/)
      __init__.py
      markets.py
      news.py
      climate.py
    Makefile                SAM makefile build — copies code into layer zip
  deps_layer/
    requirements.txt        External package list for DependencyLayer
  api_current/handler.py    GET /api/current
  api_history/handler.py    GET /api/history
  api_health/handler.py     GET /api/health
  collector/handler.py      EventBridge-triggered collector (every 15 min)
  seeder/handler.py         Manual seeder (run once after first deploy)
```

### DynamoDB schema

**jhfw-snapshots** (partition key: `ts` STRING)

| Attribute | Type | Description |
|---|---|---|
| ts | S | ISO timestamp — `"2026-04-17T15:00:00"` or `"LATEST"` sentinel |
| overall | N | Composite chaos score 0–100 |
| geo, markets, energy, trade, climate, living | N | Dimension scores |
| vix, oil, gold, spy, audusd | N | Raw market values |
| raw_json | S | Full raw values as JSON string |

**jhfw-signals** (partition key: `ts` STRING, sort key: `text` STRING)

| Attribute | Type | Description |
|---|---|---|
| ts | S | Hour-rounded timestamp of collection run |
| text | S | Signal headline text |
| category | S | `geopolitical`, `trade`, `markets`, `energy` |
| source | S | Data source domain |
| url | S | Source URL |

### Cost estimate

At 15-minute collection intervals and moderate traffic (~1000 page views/day):

| Service | Usage | Monthly cost |
|---|---|---|
| Lambda | ~3000 invocations/day × 500ms avg | ~$0.00 (free tier) |
| DynamoDB | ~17,000 writes/month, ~30,000 reads | ~$0.10 |
| API Gateway | ~30,000 requests/month | ~$0.10 |
| Amplify Hosting | Static file delivery | ~$0.00 (free tier) |
| **Total** | | **~$0–3/month** |

---

## Environment variables

### Backend (local — `backend/.env`)

```
POLL_INTERVAL_SECONDS=900   # refresh interval (default: 15 min)
```

### Lambda (set in template.yaml `Globals.Function.Environment`)

```
TABLE_PREFIX=jhfw            # DynamoDB table name prefix
SNAPSHOTS_TABLE=jhfw-snapshots
SIGNALS_TABLE=jhfw-signals
```

---

## Roadmap

- [ ] NewsAPI integration for richer headline signals
- [ ] ACLED conflict event count (free academic API)
- [ ] Nuclear threat level (Bulletin of Atomic Scientists)
- [ ] Australian petrol price tracker (FuelWatch API — WA only, free)
- [ ] Global refugee/displacement count (UNHCR API — free)
- [ ] WebSocket push for real-time frontend updates
- [ ] Share card generation (OG image per current score)
- [ ] Email/SMS alerts when score crosses a threshold
- [ ] Per-country chaos sub-scores
