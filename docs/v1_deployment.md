# GeoQA Agent V1 Deployment Guide

## Deployment Goal

V1 deployment should support a real dataset-readiness workflow with stable URLs, persistent artifacts, and a clear operational split between API and analyst UI.

## Deployment Shape

- Vercel hosts the upload web UI and lightweight API backend.
- Supabase stores production uploads, run metadata, events, and artifacts.
- A Python worker container runs heavy GeoQA processing.
- Streamlit can still run on a stateful container or VM host for deeper internal workflows.

## Required Environments

### Vercel API And Upload UI

Set these environment variables in Vercel:

- `GEOQA_API_KEY`
- `GEOQA_OUTPUT_ROOT`
- `GEOQA_AGENT_REPORT_ENABLED`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` for browser resumable uploads
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_MAX_UPLOAD_MB`
- `GEOQA_LARGE_FILE_MODE`
- `GEOQA_LARGE_FILE_MAX_UPLOAD_MB`

OpenAI credentials are not required on Vercel. Keep them on the worker runtime only.

### Python Worker And Streamlit Host

Set these environment variables on the Streamlit host:

- `GEOQA_OUTPUT_ROOT`
- `GEOQA_AGENT_REPORT_ENABLED`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_PUBLISHABLE_KEY` or `SUPABASE_ANON_KEY` for browser resumable uploads
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_WORKER_POLL_SECONDS`
- `GEOQA_WORKER_ID`
- `GEOQA_WORKER_STALE_AFTER_SECONDS`
- `GEOQA_WORKER_MAX_ATTEMPTS`
- `OPENAI_API_KEY` when live agent mode is enabled
- `GEOQA_LLM_MODEL` when live agent mode is enabled

Recommended production worker values:

- `GEOQA_WORKER_ID=geoqa-worker-prod`
- `GEOQA_WORKER_POLL_SECONDS=5`
- `GEOQA_WORKER_STALE_AFTER_SECONDS=900`
- `GEOQA_WORKER_MAX_ATTEMPTS=3`
- `GEOQA_LLM_MODEL=gpt-4.1-mini-2025-04-14`
- `GEOQA_AGENT_MAX_STEPS=6`
- `GEOQA_AGENT_OUTPUT_TOKEN_BUDGET=1600`
- `GEOQA_OPENAI_TIMEOUT_SECONDS=30`
- `GEOQA_OPENAI_MAX_RETRIES=2`

## Cloud Run Worker Pool

The production worker runs as one Cloud Run worker-pool instance in `us-east4` with `2 vCPU` and `8 GiB` memory. Build the existing Docker image, override its command with `python3 -m geoqa.production.worker`, and mount the Supabase service-role and OpenAI values from Secret Manager.

Use dedicated GCP project `geoqa-agent-prod-kv1012-20260725`. Keep `/tmp/geoqa-outputs` ephemeral; completed artifacts must be uploaded to Supabase before a job is marked ready.

## Vercel Verification

After deployment, verify:

```bash
curl https://<app>.vercel.app/health
curl https://<app>.vercel.app/config
curl -H "x-api-key: <key>" https://<app>.vercel.app/api/v1/runs
```

Expected behavior:

- `/` shows the upload dashboard, including optional target CRS/SRID reprojection.
- `/health` returns healthy status.
- `/config` returns runtime visibility and `request_id`.
- `/api/v1/*` returns `401` without `x-api-key` when `GEOQA_API_KEY` is configured.

## Streamlit Verification

Start Streamlit from the deployed host:

```bash
streamlit run streamlit_app.py
```

Verify the analyst workflow:

- run deterministic QA on the demo zipped shapefile
- inspect issue triage
- run the agent report task
- confirm consistency and grounding checks pass
- approve the draft
- generate a fix plan
- export a handoff bundle

## Storage Strategy For V1

Use Supabase as the production persistence layer for uploaded inputs, run metadata, append-only events, and generated artifacts. If Supabase is not configured, the app uses a local filesystem fallback under `GEOQA_OUTPUT_ROOT/production_mvp` for tests and local demos.

## V1 Release Gate

Before calling a deployment V1-ready:

- full test suite passes
- Vercel upload UI and health/config endpoints work
- authenticated upload and run routes work
- worker claims and processes a queued upload run
- approval queues a worker-built handoff package
- authenticated artifact buttons download successfully with `GEOQA_API_KEY` enabled
- stale running jobs can be reclaimed
- stale package jobs can be reclaimed
- large-file mode is enabled only with Supabase configured
- Streamlit demo flow works end to end
- demo output includes deterministic artifacts, agent artifacts, review status, and handoff bundle
