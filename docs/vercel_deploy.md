# GeoQA Agent Vercel Deployment (Scaffold)

## What this deployment does today

This repo now includes a minimal Vercel Python deployment scaffold using:

- `vercel.json`
- `api/index.py`

The deployed service exposes:

- `GET /` summary payload
- `GET /health` health check
- `GET /config` runtime config visibility

## Why this is a scaffold (important)

The full GeoQA Streamlit workflow is stateful and heavy for serverless limits.

Use this Vercel deployment for:

- lightweight health/config checks
- integration placeholders
- initial environment validation

Use container/VM hosting for:

- full Streamlit analyst UI
- heavier geospatial QA runs
- large artifact generation and persistent run storage

## Deploy steps

1. Connect the GitHub repo to Vercel.
2. Keep project root as repository root.
3. Set env vars in Vercel:
   - `OPENAI_API_KEY` (optional for scaffold endpoints)
   - `GEOQA_LLM_MODEL`
   - `GEOQA_AGENT_REPORT_ENABLED`
   - `GEOQA_OUTPUT_ROOT`
4. Deploy.
5. Verify:
   - `/health`
   - `/config`

## Next phase to reach full Vercel product shape

If you want deeper Vercel-native deployment later, move from Streamlit-first runtime to:

- API-first endpoints for run/create/review/export
- external object storage for artifacts
- background workers for heavy jobs
- frontend app consuming those APIs
