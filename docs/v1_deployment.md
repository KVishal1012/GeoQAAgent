# GeoQA Agent V1 Deployment Guide

## Deployment Goal

V1 deployment should support a real dataset-readiness workflow with stable URLs, persistent artifacts, and a clear operational split between API and analyst UI.

## Deployment Shape

- Vercel hosts the lightweight API backend.
- Streamlit runs on a stateful container or VM host.
- Both deployments share the same repo branch and runtime configuration model.

## Required Environments

### Vercel API

Set these environment variables in Vercel:

- `GEOQA_API_KEY`
- `GEOQA_OUTPUT_ROOT`
- `GEOQA_AGENT_REPORT_ENABLED`

Optional for live agent workflows:

- `OPENAI_API_KEY`
- `GEOQA_LLM_MODEL`

### Streamlit Host

Set these environment variables on the Streamlit host:

- `GEOQA_OUTPUT_ROOT`
- `GEOQA_AGENT_REPORT_ENABLED`
- `OPENAI_API_KEY` when live agent mode is enabled
- `GEOQA_LLM_MODEL` when live agent mode is enabled

## Vercel Verification

After deployment, verify:

```bash
curl https://<app>.vercel.app/health
curl https://<app>.vercel.app/config
curl -H "x-api-key: <key>" https://<app>.vercel.app/api/v1/runs/<run_id>
```

Expected behavior:

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

Use persistent disk for `GEOQA_OUTPUT_ROOT` on the Streamlit host.

V1 keeps Vercel API state under `GEOQA_OUTPUT_ROOT/api_runs`. This is acceptable for the MVP, but the next production step is object storage plus a durable queue.

## V1 Release Gate

Before calling a deployment V1-ready:

- full test suite passes
- Vercel health/config endpoints work
- authenticated API route works
- Streamlit demo flow works end to end
- demo output includes deterministic artifacts, agent artifacts, review status, and handoff bundle
