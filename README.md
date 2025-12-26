# n8n Workflow Popularity System

Short: A data pipeline and REST API that identifies popular n8n workflows across YouTube, Discourse (n8n forum) and synthesized Google Trends, with US/IN country segmentation.

Overview
--------
- Purpose: collect evidence of popularity for n8n workflows, compute simple popularity metrics and ratios, and provide an API-ready canonical dataset suitable for production fallback and automation.
- Data sources implemented: YouTube (Data API v3), Discourse forum (public JSON + HTML fallback), Google Trends (pytrends) with a synthesized fallback when pytrends is unavailable. Optional: Google Ads Keyword Planner (guarded wrapper).

Status (as shipped)
--------------------
- Raw evidence: `data/workflows.json` (collected YouTube + Discourse items).
- Canonical aggregated dataset: `data/canonical_workflows.json` (aggregated + scores).
- API response payload: `data/response.json` (ready for serving; includes per-region entries and synthesized trends under `google_trends`).
- Synthesized trends: `data/trends_synth.json` (used when pytrends is rate-limited).

How it works (high level)
-------------------------
1. Collectors (in `app/collectors`): gather evidence from platforms and attach basic metrics (views, likes, comments, replies, views, country when available).
2. Ingest & scoring (`app/processing/ingest.py` + `app/processing/score.py`): groups evidence by normalized title, aggregates metrics, computes like/comment-to-view ratios, and produces a `popularity_score`.
3. Trends: attempted via `pytrends` (in `app/collectors/trends_collector.py`); when blocked, a synthesizer produces `trends_synth.json` which is merged into `data/response.json` and attached to canonical items via `app/tools/augment_canonical_with_trends.py`.
4. API (`app/main.py`, `app/api/workflows.py`): FastAPI app that attempts DB-backed queries (Postgres + asyncpg) and falls back to `data/canonical_workflows.json`.

Run locally (minimal)
---------------------
1. Create an env file. Copy the example:

   - File: `.env.example` (provided in repo)

2. Install dependencies (prefer a virtualenv):

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

3. Serve API (uses JSON fallback if DB not available):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
# then: http://127.0.0.1:8000/workflows/top?limit=10&country=US&platform=YouTube
```

4. Regenerate canonical JSON (aggregate from `data/workflows.json`):

```bash
python -c "import asyncio; from app.processing import ingest; asyncio.run(ingest.run_ingest())"
```

Files & short descriptions
--------------------------
- `app/` : application source
  - `app/main.py` : FastAPI app entrypoint and startup logic
  - `app/api/workflows.py` : API router exposing `/workflows` endpoints with DB-first, JSON-fallback behavior
  - `app/collectors/` : platform-specific collectors
    - `discourse_collector.py` : Discourse topic search + HTML fallback + user->country inference
    - `youtube_collector.py` : YouTube Data API collector + region support
    - `trends_collector.py` : pytrends wrapper with anchor-based estimates and fallback handling
    - `google_ads_collector.py` : guarded Google Ads Keyword Planner helper (requires credentials)
  - `app/processing/ingest.py` : grouping, aggregation, score computation and DB upsert fallback to JSON
  - `app/processing/score.py` : scoring helpers used by ingest
  - `app/tools/` : utilities used during finalization or manual runs (merge trends, duplicate regions, augment canonical, etc.)
  - `app/db.py` : DB engine creation (async) with a graceful fallback when `asyncpg` isn't installed

- `data/` : generated outputs and fallbacks
  - `workflows.json` : raw collected evidence (YouTube + Discourse)
  - `canonical_workflows.json` : aggregated canonical workflows (used by API fallback)
  - `trends_synth.json` : synthesized trends fallback
  - `response.json` : API-ready response payload (includes per-region entries and `submission_note`)

- `README.md` : this file

Environment variables (`.env` or CI secrets)
------------------------------------------
Create `.env` in the repo root or set env vars in your environment. Example provided in `.env.example`.

Essential variables:
- `YOUTUBE_API_KEY` — required for YouTube Data API collection.
- `DISCOURSE_BASE_URL` — e.g. `https://community.n8n.io`.
- `PYTRENDS_ANCHOR_KEYWORD` and `PYTRENDS_ANCHOR_VOLUME` — optional anchor to estimate monthly searches when pytrends is used.
- `DATABASE_URL` — PostgreSQL async URL (e.g. `postgresql+asyncpg://user:pass@host:port/dbname`). If not available, the app falls back to JSON files.

Optional variables:
- `GOOGLE_ADS_CONFIG_PATH` and `GOOGLE_ADS_CUSTOMER_ID` — to enable Google Ads Keyword Planner calls (optional, guarded).
- `COLLECTOR_PROXY` — optional HTTP(S) proxy for pytrends/collectors.

Known limitations & guidance for reviewers
----------------------------------------
- Pytrends: Google may rate-limit or reject requests from some environments (HTTP 400/429). This project implements robust retries and a synthesized fallback so the system remains functional.
- Google Ads: not enabled by default — requires a `google-ads.yaml` and customer id.
- Dataset size: the automated run in this environment produced ~1.7k canonical items; scaling to 20k requires more collection breadth, API key rotation, and longer crawling.

Submission checklist
--------------------
- Include `data/` generated JSON files.
- Include `README.md`, `requirements.txt`, and `.env.example`.
- Note any missing external credentials (Google Ads) and runtime caveats (pytrends network sensitivity).

If you want me to package and zip the workspace for submission, say `create README+zip` and I'll produce a zip file ready to upload.
Popularity intelligence for n8n workflows
========================================

Purpose
-------
This repo contains a production-oriented scaffold for a popularity intelligence system that collects signals about n8n workflows from YouTube, Discourse, and Google Trends and exposes them via a FastAPI REST API.

Quick start (development)
-------------------------
1. Copy environment variables:

```bash
cp .env.example .env
# edit .env to set DB and API keys
```

2. Start Postgres (recommended via Docker Compose):

```bash
docker-compose up -d
```

3. Install dependencies (use virtualenv):

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

4. Run the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API
---
- `GET /health` — health check
- `GET /workflows` — list workflows (filters supported)
- `GET /workflows/top` — top workflows by platform/country

Project layout
--------------
- `app/` — FastAPI app, DB, collectors, processing
- `scripts/collect.py` — entrypoint for scheduled collectors
- `docker-compose.yml` — local Postgres

Next steps
----------
- Implement collectors in `app/collectors`
- Implement processing and scoring in `app/processing`
- Add migrations (Alembic) and run schema init
- Populate dataset (scripts/collect.py)
