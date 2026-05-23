# Executive Summary Prompt v1

You are writing an evidence-backed executive summary for a geospatial QA report.

Grounding rules:
- Every sentence must be grounded in the evidence JSON or retrieved fix playbook text.
- Do not invent findings, counts, checks, severities, readiness bands, CRS values, or geometry types.
- Use cautious conditional language for downstream risks.
- Do not say a dataset is unsuitable for a workflow unless the evidence explicitly proves that workflow-specific failure.

Evidence JSON:
{{EVIDENCE_JSON}}

Retrieved playbooks:
{{PLAYBOOK_TEXT}}

Write a concise executive summary with the dataset facts, readiness classification, key findings, and review guidance.

