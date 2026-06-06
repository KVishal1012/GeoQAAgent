# GeoQA Agent Vercel Deployment (Upload MVP Phase)

## What this deployment does now

This repo includes a Vercel Python upload UI and API backend using:

- `vercel.json`
- `api/index.py`

Public endpoints:

- `GET /` renders the upload dashboard
- `GET /health` returns JSON health status
- `GET /config` returns JSON runtime visibility

Authenticated API endpoints:

- `POST /api/v1/uploads`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `POST /api/v1/runs/{run_id}/review`
- `GET /api/v1/runs/{run_id}/artifacts`

## Runtime model

- Upload-created run submission follows an async lifecycle: `queued -> running -> completed|failed`.
- A Python worker processes queued uploads outside the Vercel request path.
- Deterministic QA remains the source of truth.
- API responses return structured JSON with stable error envelopes.

## Required environment variables

- `GEOQA_OUTPUT_ROOT` (local fallback and worker output root)
- `GEOQA_API_KEY` (required to access `/api/v1/*` routes)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GEOQA_UPLOAD_BUCKET`
- `GEOQA_ARTIFACT_BUCKET`
- `GEOQA_MAX_UPLOAD_MB`
- `GEOQA_WORKER_POLL_SECONDS`

Optional:

- `OPENAI_API_KEY`
- `GEOQA_LLM_MODEL`
- `GEOQA_AGENT_REPORT_ENABLED`

## Deploy steps

1. Connect `KVishal1012/GeoQAAgent` to Vercel.
2. Select branch `V3.0`.
3. Keep project root as repository root.
4. Set the environment variables above.
5. Deploy.

## Verification checklist

1. `GET /` renders the GeoQA Agent upload UI.
2. `GET /health` returns `{"status": "healthy"}`.
3. `GET /config` returns runtime visibility plus `request_id`.
4. `POST /api/v1/uploads` without `x-api-key` returns `401` with:
   - `error.code = unauthorized`
5. `POST /api/v1/runs` with valid `x-api-key` returns `202` and:
   - `run_id`
   - `status = queued`
6. Poll `GET /api/v1/runs/{run_id}` until completed.
7. Confirm `GET /api/v1/runs/{run_id}/artifacts` returns artifact manifest metadata.

## Error envelope contract

All `/api/v1/*` errors follow:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {}
  },
  "request_id": "req-..."
}
```

## Notes on production shape

- This phase keeps Streamlit as a local/stateful operator console for deeper internal workflows.
- Vercel is the upload/status/download web layer.
- Supabase stores production uploads, run metadata, events, and artifacts.
- The Python worker performs heavy GeoQA processing outside Vercel.
