# GeoQA Agent V1 Production MVP

## Goal

The V1 production MVP is an uploadable GeoQA web app. Vercel hosts the web UI and lightweight JSON API. A Python worker performs the heavy GeoPandas/GeoQA processing outside the request path.

## Runtime Shape

- Vercel serves `/`, `/health`, `/config`, and `/api/v1/*`.
- Users upload `.geojson`, `.gpkg`, or zipped shapefile inputs from `/`.
- Upload runs are stored as queued jobs.
- The worker downloads queued uploads, runs `run_geoqa(...)`, stores artifacts, and marks the run completed or failed.
- Supabase is the production persistence target. If Supabase env vars are absent, the app uses a local filesystem fallback for tests and local demos.

## Supabase Setup

Create two private storage buckets:

- `geoqa-uploads`
- `geoqa-artifacts`

Apply the migration:

```bash
supabase/migrations/001_v1_production_mvp.sql
```

Required Vercel and worker environment variables:

```bash
GEOQA_API_KEY=<internal-api-key>
SUPABASE_URL=<project-url>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
GEOQA_UPLOAD_BUCKET=geoqa-uploads
GEOQA_ARTIFACT_BUCKET=geoqa-artifacts
GEOQA_MAX_UPLOAD_MB=100
GEOQA_WORKER_POLL_SECONDS=5
```

Optional agent settings:

```bash
OPENAI_API_KEY=<openai-key>
GEOQA_LLM_MODEL=<model>
GEOQA_AGENT_REPORT_ENABLED=true
```

## Copy-Paste MVP Flow

Start the worker locally or on a stateful container host:

```bash
python -m geoqa.production.worker
```

Deploy Vercel and open:

```bash
https://geoqa-agent.vercel.app
```

Use the page to:

- paste the API key if configured
- upload a `.geojson`, `.gpkg`, or zipped shapefile
- queue the QA run
- wait for status to become `completed`
- download `qa_report.md`, `issues.csv`, `summary.json`, and `run_record.json`

## Smoke Tests

```bash
curl https://geoqa-agent.vercel.app/health
curl https://geoqa-agent.vercel.app/config
python -m pytest tests/test_vercel_api.py tests/test_config.py
```

Expected results:

- `/` displays the upload UI.
- unsupported file types are rejected.
- valid uploads create queued runs.
- the worker processes queued runs.
- completed runs expose downloadable QA artifacts.
