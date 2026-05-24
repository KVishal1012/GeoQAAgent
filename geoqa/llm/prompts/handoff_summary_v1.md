Write a grounded handoff summary for task `{{TASK_NAME}}`.

Rules:
- Use only deterministic evidence, tool trace outputs, and retrieved playbook text.
- Focus on readiness, key findings, remediation status, and what is included in the handoff package.
- Do not invent missing artifacts.
- Use plain-English wording.

Deterministic evidence:
{{EVIDENCE_JSON}}

Tool trace:
{{TOOL_TRACE_JSON}}

Retrieved playbooks:
{{PLAYBOOK_TEXT}}
