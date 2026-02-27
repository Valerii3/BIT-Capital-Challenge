## Backend (Railway)

FastAPI service that owns all DB access and pipeline execution.

### Endpoints

- `GET /health`
- `GET /stocks`
- `POST /stocks`
- `DELETE /stocks/{stock_id}`
- `POST /stocks/{stock_id}/enrich`
- `GET /events`
- `POST /pipeline/run`

### Env vars

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `BACKEND_CORS_ORIGINS` (comma-separated, e.g. `https://your-vercel-app.vercel.app`)

### Local run

```bash
cd /Users/Valerii.Ovchinnikov/Documents/repo/BIT-Capital-Challenge
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Scheduled pipeline command

```bash
python -m backend.run_pipeline
```

Use Railway Scheduler to run the command on your cron interval.
