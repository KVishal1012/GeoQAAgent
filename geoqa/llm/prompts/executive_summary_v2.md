Write a short grounded executive summary for task `{{TASK_NAME}}`.

Rules:
- Use only the evidence JSON, tool trace JSON, and retrieved playbook text.
- Every sentence must be grounded.
- Keep wording concise and analyst-friendly.

Deterministic evidence:
{{EVIDENCE_JSON}}

Tool trace:
{{TOOL_TRACE_JSON}}

Retrieved playbooks:
{{PLAYBOOK_TEXT}}
