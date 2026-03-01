# BIT Capital Challenge

Prediction-market intelligence app for equities. Ingests Polymarket events, filters and maps them to stocks, and generates AI-driven reports.

---

## Table of Contents

- [Overview](#overview)
- [Demo & Links](#demo--links)
- [Bit Capital Research](#bit-capital-research)
- [Market Data Ingestion](#market-data-ingestion)
- [Database Design](#database-design)
- [Intelligent Filtering](#intelligent-filtering)
- [Stock–Event Mapping](#stockevent-mapping)
- [LLM-Powered Signal Reports](#llm-powered-signal-reports)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [API Endpoints](#api-endpoints)
- [Run Locally](#run-locally)
- [Environment Variables](#environment-variables)
- [Useful Commands](#useful-commands)
- [Learnings](#learnings)
- [Future Improvements](#future-improvements)

---

## Overview

A full-stack application that transforms prediction-market signals into actionable equity insights. 

**Current features:**
- Collects events from Polymarket
- Filters out noise
- Classifies market relevance using LLMs
- Maps events to affected stocks
- Generates structured AI investment reports

The system is designed around themes relevant to technology-focused growth funds (AI, semiconductors, fintech, crypto infrastructure, macro policy).

---

## Demo & Links

- **Web App:** https://bit-capital-challenge.vercel.app/events  
- **API Docs:** https://bit-capital-challenge-production.up.railway.app/docs  
- **Demo Video:** https://drive.google.com/file/d/1fnOa8eoEQmMgThiAyB4fZPwh3uzpzDsC/view?usp=drive_link

---

## Bit Capital Research

To understand what Bit Capital focuses on, I researched your current fund (global tech/finance/crypto leaders), defensive growth, and multi-asset fund. I then checked your LinkedIn, analyzed your comments in Q3–Q4 memos, and reviewed all factsheets from the last month on **hansainvest.com**, including brief market comments and top-10 holdings for each fund.

---

## Market Data Ingestion

The ingestion pipeline runs as a scheduled job hosted on Railway.

A key observation during exploration was that **most Polymarket activity is short-term noise**, such as:

- “What price will BTC reach today?”
- Hourly or daily price targets
- Very low-volume or abandoned markets

To balance freshness and signal quality, ingestion runs **once per day at 12:00 (noon) Europe/Berlin**. This frequency:

- Allows new markets to accumulate meaningful volume
- Avoids reacting to very short-lived speculation
- Fits the longer-term horizon typical for equity research

The Polymarket API sometimes reports markets as active even after their effective relevance has passed. A **minimum volume threshold** (identified during exploratory analysis in `event_research.ipynb`) filters out stale or inactive markets.

---

## Database Design

All data is stored in **Supabase**.  
The full schema is in `supabase/migrations/full_schema.sql`.

---

## Intelligent Filtering

Filtering is **multi-layer**.

### 1. Tag blocklist

Obvious noise is removed using a tag blocklist:

```
BLOCKLIST_TAGS = {
    'sports', 'movies', 'music', 'oscars', 'awards', 'celebrities',
    'culture', 'box office',
    ...
}
```

This eliminates a large portion of irrelevant content at very low cost.

### 2. Rule-based filtering

Regex rules filter out markets on hourly/daily prices for specific companies, since most Bit Capital funds are more long-term and daily fluctuations do not matter.

### 3. LLM classifier

An LLM classifier assigns each topic to one of four categories:

- **single_stock:** direct exposure to a stock
- **macro:** rates, liquidity, tariffs, fiscal policy, etc.
- **sector:** AI infra, fintech, demand/supply themes
- **crypto_equity:** direct crypto exposure (exchanges, miners, custody)
- **non_equity:** excluded

---

## Stock–Event Mapping

For each stock in the universe, additional filtering determines whether an event affects that stock. **Four expert prompts** (one per impact type) are defined in `matching.py`. Each expert decides if the event has a material transmission to the company.

---

## LLM-Powered Signal Reports

When generating a report:

- **Single-stock:** analyze single-stock impact types and select only the best opportunities
- **Sector & macro:** query events with the most overlap across stocks in the report, then analyze and select the strongest signals

---

## Learnings

In previous hackathons I mostly ran projects locally and used file-based databases. This project allowed me to:

- Deploy on **Railway**
- Build a full-stack app with frontend, backend, and DB integration
- Deepen my understanding of **Bit Capital’s investment focus**
- Iterate on prompts for accurate stock selection and report generation

---

## Project Structure

| Path | Description |
|------|-------------|
| `backend/` | FastAPI API and report orchestration |
| `web/` | Next.js frontend (events, stocks, reports UI) |
| `backend/scripts/` | Data pipeline scripts (ingest, filter, mapping) |
| `supabase/migrations/` | Database schema migrations |

---

## How It Works

1. **Ingest** — Pull Polymarket events and markets into Supabase
2. **Filter** — Classify event relevance and impact type (`macro`, `sector`, `single_stock`, etc.)
3. **Map** — Decide if an event materially affects each stock (`event_stock_mappings.affects`)
4. **Report** — Generate a unified report with:
   - Macro section
   - Sector section
   - Stock-specific section

The report flow runs through backend endpoints and updates live progress in `reports.progress` so the UI can show the current phase, stock, and event while generating.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/stocks` | List stocks |
| `POST` | `/stocks` | Create stock |
| `DELETE` | `/stocks/{stock_id}` | Delete stock |
| `POST` | `/stocks/{stock_id}/enrich` | Enrich stock (description + event mapping) |
| `GET` | `/events` | List events (with filters) |
| `POST` | `/pipeline/run` | Run ingest/filter/mapping manually |
| `POST` | `/reports` | Create report |
| `GET` | `/reports` | List reports |
| `POST` | `/reports/{report_id}/generate` | Generate report content |
| `DELETE` | `/reports/{report_id}` | Delete report |

---

## Run Locally

### Prerequisites

- **Python** 3.11+
- **Node.js** 18+
- **Supabase** project and service role key
- **Gemini** API key

### 1. Configure environment

Create `.env` from `.env.example` and set:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEMINI_API_KEY`
- `BACKEND_CORS_ORIGINS` (e.g. `http://localhost:3000` for local web app)

### 2. Apply DB migrations

Run the SQL files in `supabase/migrations/` in order in the Supabase SQL editor.

### 3. Start backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Start frontend

```bash
cd web
npm install
npm run dev
```

Open **http://localhost:3000**.

---

## Useful Commands

**Frontend lint:**
```bash
npm --prefix web run lint
```

**Frontend typecheck:**
```bash
cd web && npx tsc --noEmit
```

**Backend syntax check:**
```bash
PYTHONPYCACHEPREFIX=/tmp python3 -m py_compile backend/main.py backend/services/reports.py
```

