# V1 Case Study: Centreline Intersection Dataset Readiness

## Dataset

The V1 demo uses `demo/input/centreline_intersections_sample.zip`, a 50-feature sample from a Centreline Intersection dataset.

Dataset metadata from GeoQA:

- filename: `centreline_intersections_sample.zip`
- feature count: 50
- geometry type: MultiPoint
- CRS: EPSG:4326

## Result

GeoQA classified the dataset as `needs_review` with a readiness score of `87/100`.

The run produced 4 findings:

- 1 medium-severity duplicate geometry finding
- 3 low-severity null-heavy column findings

The agent-assisted report passed:

- report consistency validation
- hallucination/grounding validation

## Why This Matters

The duplicate geometry finding may be valid for intersection data in some workflows, but it should be reviewed before the dataset is used in spatial joins, downstream reporting, or network analysis.

The null-heavy columns indicate fields that may need to be populated, removed, or explained before the dataset is handed to another team.

## Handoff Value

The V1 output package gives downstream teams:

- deterministic QA report
- issue CSV
- run summary
- run record
- agent report draft and approved report
- validation results
- review status and history
- agent session and trace artifacts

## Reproduce The Case Study

Run deterministic QA and V4 agent report generation:

```bash
python app.py demo/input/centreline_intersections_sample.zip --output-dir demo/output --agent-run --agent-task report --agent-max-steps 4 --llm-provider static --static-report-file demo/output/static_v4_report.md --approve-agent-report --reviewer-name "Demo Reviewer"
```

Run Streamlit for analyst review:

```bash
streamlit run streamlit_app.py
```

Verify Vercel API health after deployment:

```bash
curl https://<app>.vercel.app/health
```
