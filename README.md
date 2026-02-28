# BIT Capital Challenge

Prediction-market intelligence app for equities. It ingests Polymarket events, filters and maps them to stocks, and generates AI-driven reports.

Try it out: [https://bit-capital-challenge.vercel.app/events](https://bit-capital-challenge.vercel.app/events)

[Demo](https://drive.google.com/file/d/1fnOa8eoEQmMgThiAyB4fZPwh3uzpzDsC/view?usp=drive_link)

## Project Structure

- `backend/` FastAPI API and report generation orchestration.
- `web/` Next.js frontend (events, stocks, reports UI).
- `backend/scripts/` data pipeline scripts (ingest/filter/mapping helpers).
- `supabase/migrations/` database schema migrations.

## How It Works

1. **Ingest**: Pull Polymarket events/markets into Supabase tables.
2. **Filter**: Classify event relevance and impact type (`macro`, `sector`, `single_stock`, etc.).
3. **Map**: Decide if an event materially affects each stock (`event_stock_mappings.affects`).
4. **Report**: Generate a unified report composed of:
   - macro section,
   - sector section,
   - stock-specific section.

The report flow runs through backend endpoints and updates live progress in `reports.progress` so UI can display current phase/stock/event while generating.

## Backend API (main)

- `GET /health`
- `GET /stocks`
- `POST /stocks`
- `DELETE /stocks/{stock_id}`
- `POST /stocks/{stock_id}/enrich`
- `GET /events`
- `POST /reports`
- `GET /reports`
- `POST /reports/{report_id}/generate`
- `DELETE /reports/{report_id}`

## Run Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- Supabase project + service role key
- Gemini API key

### 1) Configure env

Create `.env` from `.env.example` and fill:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `BACKEND_CORS_ORIGINS` (for local web app, usually `http://localhost:3000`)

### 2) Apply DB migrations

Run SQL files in `supabase/migrations/` in order in your Supabase SQL editor.

### 3) Start backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4) Start frontend

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Useful Commands

- Frontend lint:

```bash
npm --prefix web run lint
```

- Frontend typecheck:

```bash
cd web && npx tsc --noEmit
```

- Backend syntax check:

```bash
PYTHONPYCACHEPREFIX=/tmp python3 -m py_compile backend/main.py backend/services/reports.py
```
