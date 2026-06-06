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
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_WORKER_POLL_SECONDS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_MAX_UPLOAD_MB`

Optional for live agent workflows:

- `OPENAI_API_KEY`
- `GEOQA_LLM_MODEL`

### Python Worker And Streamlit Host

Set these environment variables on the Streamlit host:

- `GEOQA_OUTPUT_ROOT`
- `GEOQA_AGENT_REPORT_ENABLED`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_WORKER_POLL_SECONDS`
- `OPENAI_API_KEY` when live agent mode is enabled
- `GEOQA_LLM_MODEL` when live agent mode is enabled

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
- worker processes a queued upload run
- Streamlit demo flow works end to end
- demo output includes deterministic artifacts, agent artifacts, review status, and handoff bundle
