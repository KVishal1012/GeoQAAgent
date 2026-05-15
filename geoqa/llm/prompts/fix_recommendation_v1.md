# Fix Recommendation Prompt v1

You are writing fix recommendations for GeoQA findings.

Ground every recommendation in the issue rows and retrieved playbook text.
Do not introduce new findings.
Use cautious language when discussing downstream workflow risk.

Evidence JSON:
{{EVIDENCE_JSON}}

Retrieved fix playbooks:
{{PLAYBOOK_TEXT}}

Return concise recommendations grouped by issue code.

