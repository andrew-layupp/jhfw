# justhowfuckedarewe.com — Global Chaos Index

A live dashboard tracking global chaos across 6 dimensions using freely available data APIs — no paid subscriptions required.

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

## Quick start

### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the backend

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On first run, the backend will:
1. Initialise a local `chaos.db` SQLite database
2. **Backfill 6 months of history** from yfinance (takes ~60s)
3. Start polling all data sources every 15 minutes

### 3. Open the frontend

Open `frontend/index.html` directly in your browser. It will connect to `http://localhost:8000` by default.

To point it at a remote backend, set the global before the script runs:

```html
<script>window.JHFW_BACKEND = 'https://your-backend.railway.app';</script>
```

### API endpoints

```
GET /api/health     — health check + snapshot count
GET /api/current    — latest chaos scores + signals
GET /api/history    — daily snapshots for past N days (?days=180)
GET /api/refresh    — force an immediate data refresh
```

## Environment variables

Create a `.env` file in `backend/`:

```
POLL_INTERVAL_SECONDS=900   # how often to refresh (default: 15 min)
```

Optional — add these when you have the keys for richer signals:

```
NEWS_API_KEY=your_key_here   # newsapi.org free tier (100 req/day)
ACLED_API_KEY=your_key_here  # acleddata.com free for researchers
```

## Deployment

### Railway (recommended — free tier available)

```bash
# From the backend directory
railway init
railway up
```

Set `PORT` env var — Railway auto-injects it. Update `frontend/index.html`:
```js
window.JHFW_BACKEND = 'https://your-project.up.railway.app';
```

### Vercel (frontend only)

Drop `frontend/index.html` into a Vercel project. The backend needs a separate server.

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t jhfw .
docker run -p 8000:8000 -v $(pwd)/data:/app jhfw
```

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
