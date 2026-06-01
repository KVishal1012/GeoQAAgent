# GeoQA Agent Vercel Deployment (API Phase)

## What this deployment does now

This repo includes a Vercel Python API backend using:

- `vercel.json`
- `api/index.py`

Public endpoints:

- `GET /`
- `GET /health`
- `GET /config`

Authenticated API endpoints:

- `POST /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `POST /api/v1/runs/{run_id}/review`
- `GET /api/v1/runs/{run_id}/artifacts`

## Runtime model

- Run submission follows an async lifecycle: `queued -> running -> completed|failed`.
- Deterministic QA remains the source of truth.
- API responses return structured JSON with stable error envelopes.

## Required environment variables

- `GEOQA_OUTPUT_ROOT` (for run outputs and API run state files)
- `GEOQA_API_KEY` (required to access `/api/v1/*` routes)

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

1. `GET /health` returns `{"status": "healthy"}`.
2. `GET /config` returns runtime visibility plus `request_id`.
3. `POST /api/v1/runs` without `x-api-key` returns `401` with:
   - `error.code = unauthorized`
4. `POST /api/v1/runs` with valid `x-api-key` returns `202` and:
   - `run_id`
   - `status = queued`
5. Poll `GET /api/v1/runs/{run_id}` until completed.
6. Confirm `GET /api/v1/runs/{run_id}/artifacts` returns artifact manifest metadata.

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

- This phase keeps Streamlit as a local/stateful operator console.
- Vercel API is additive and does not replace CLI/Streamlit workflows.
- For larger workloads, pair this API with external object storage and background workers.
