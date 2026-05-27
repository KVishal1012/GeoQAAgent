# GeoQA Agent V4 Release Notes

## Theme

V4 upgrades GeoQA Agent into a real OpenAI-backed, tool-using analyst agent while preserving deterministic QA as the source of truth.

The V4 agent runs only on local GeoQA evidence and internal tools.

## What V4 Adds

- Bounded agent session runtime for three tasks:
  - `report`
  - `fix_plan`
  - `handoff`
- Internal GeoQA-only tool surface for evidence loading, issue paging, remediation, comparison, and handoff export
- Session and trace transparency artifacts:
  - `agent_session.json`
  - `agent_trace.json`
- First-class Streamlit `Run Agent` workflow
- Backward-compatible `--agent-report` path routed to the V4 `report` task

## Evidence Contract

Every AI-generated sentence must be grounded in:

- `summary.json`
- `issues.csv`
- `run_record.json`
- retrieved fix playbook text
- internal tool outputs derived from the above

## Validation And Governance

- `report_consistency.json` remains a blocking check
- `hallucination_check.json` remains a blocking check
- `review_status.json` tracks current review state
- `review_history.jsonl` remains append-only review audit history
- `agent_report.md` is produced only after approval

## New/Updated Artifacts

V4 agent artifacts:

- `agent_session.json`
- `agent_trace.json`
- `agent_report_draft.md`
- `agent_report.json`
- `report_consistency.json`
- `hallucination_check.json`
- `review_status.json`
- `review_history.jsonl`
- `agent_report.md` after approval only

## Recommended V4 Demo Command

```bash
python app.py demo/input/centreline_intersections_sample.zip --output-dir demo/output --agent-run --agent-task report --agent-max-steps 4 --llm-provider static --static-report-file demo/output/static_v4_report.md --approve-agent-report --reviewer-name "Demo Reviewer"
```

## Notes

- OpenAI remains the only live provider path in V4.
- The agent remains single-agent by design in this release.
- No autonomous data mutation/remediation is introduced in V4.
