# GeoQA Agent V1 Production MVP

## Goal

The V1 production MVP is an uploadable GeoQA web app. Vercel hosts the web UI and lightweight JSON API. A Python worker performs the heavy GeoPandas/GeoQA processing outside the request path.

## Runtime Shape

- Vercel serves `/`, `/health`, `/config`, and `/api/v1/*`.
- Users upload `.geojson`, `.gpkg`, or zipped shapefile inputs from `/`.
- Users may optionally enter a target CRS/SRID, such as `EPSG:4326`, `EPSG:3857`, `4326`, or `3857`, to reproject before QA.
- Production uploads use direct Supabase Storage upload sessions; local multipart upload remains a dev/test fallback.
- Upload runs are stored as queued jobs.
- The worker downloads queued uploads, runs `run_geoqa(...)`, stores artifacts, and marks the run completed or failed.
- Supabase is the production persistence target. If Supabase env vars are absent, the app uses a local filesystem fallback for tests and local demos.

## Supabase Setup

Create two private storage buckets:

- `geoqa-uploads`
- `geoqa-artifacts`

Apply the migrations in order:

```bash
supabase/migrations/001_v1_production_mvp.sql
supabase/migrations/002_v11_worker_claims_large_uploads.sql
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
GEOQA_LARGE_FILE_MODE=false
GEOQA_LARGE_FILE_MAX_UPLOAD_MB=1024
GEOQA_WORKER_ID=geoqa-worker
GEOQA_WORKER_STALE_AFTER_SECONDS=900
GEOQA_WORKER_MAX_ATTEMPTS=3
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
- optionally enter a target CRS/SRID for reprojection
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
- target SRIDs are normalized to EPSG CRS strings before processing.
- the worker processes queued runs.
- completed runs expose downloadable QA artifacts.

## V1.1 Large-File Mode

Large-file mode is intentionally gated behind Supabase:

- Keep `GEOQA_LARGE_FILE_MODE=false` for the default 100 MB MVP path.
- Set `GEOQA_LARGE_FILE_MODE=true` only after Supabase buckets and the worker are running.
- V1.1 allows up to `GEOQA_LARGE_FILE_MAX_UPLOAD_MB=1024` through direct Supabase upload sessions.
- The Vercel multipart fallback remains capped by `GEOQA_MAX_UPLOAD_MB` and is not intended for 1 GB files.

## V1.1 Worker Safety

The worker now claims jobs before processing and writes heartbeat metadata. This prevents duplicate workers from processing the same queued run and allows stale `running` jobs to be reclaimed after `GEOQA_WORKER_STALE_AFTER_SECONDS`. Failed jobs retry until `GEOQA_WORKER_MAX_ATTEMPTS`, then remain `failed` with a safe user-facing error.
