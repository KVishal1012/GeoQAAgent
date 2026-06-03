# GeoQA Agent V1 MVP Release Notes

## Theme

V1 makes GeoQA Agent a usable dataset-readiness MVP for real-world GIS and infrastructure workflows.

The product combines deterministic spatial QA, evidence-backed agent assistance, human review, and handoff packaging. The goal is a practical deployed workflow, not a research prototype.

## V1 Product Definition

GeoQA Agent V1 lets a team:

- reference or upload a geospatial dataset
- run deterministic QA checks
- inspect issue findings in plain language
- generate grounded AI-assisted reports or fix plans
- validate AI output against evidence
- approve or reject the draft
- export a handoff bundle for downstream teams

## V1 Deployment Shape

V1 uses a two-part deployment model:

- Vercel API for lightweight integration endpoints and deployment health checks
- Streamlit on a stateful host for the main analyst workflow and artifact generation

This keeps the system usable now while avoiding the runtime and storage limits of serverless-only geospatial processing.

## Included Capabilities

- Deterministic QA for GeoJSON, GPKG, and zipped shapefiles
- Readiness scoring and severity summaries
- Agent runtime with report, fix-plan, and handoff tasks
- Report consistency and hallucination checks
- Human approval/rejection workflow
- Recent-run browsing and issue triage
- Run comparison
- Handoff bundle export
- Vercel API v1 run/review/artifact endpoints

## Primary V1 Demo

The primary V1 demo uses `demo/input/centreline_intersections_sample.zip` and produces a `needs_review` result with:

- 50 features
- MultiPoint geometry
- EPSG:4326 CRS
- readiness score of 87
- 4 findings
- passing consistency and grounding checks

## Known V1 Limits

- V1 does not mutate or repair source datasets automatically.
- V1 does not provide multi-user auth or roles beyond API key gating.
- V1 does not use durable object storage or a production queue yet.
- V1 keeps Streamlit as the main analyst UI rather than a full custom web frontend.
- V1 uses OpenAI as the live LLM provider path.

## Product Claim

GeoQA Agent V1 produces evidence-backed geospatial QA outputs that can be reviewed, approved, and handed off with traceability.
