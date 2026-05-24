Write a grounded remediation summary for task `{{TASK_NAME}}`.

Rules:
- Use only deterministic evidence, tool trace outputs, and retrieved playbook text.
- Focus on recommended actions, affected records, and any conditions that should be reviewed before handoff.
- Use plain-English wording.

Deterministic evidence:
{{EVIDENCE_JSON}}

Tool trace:
{{TOOL_TRACE_JSON}}

Retrieved playbooks:
{{PLAYBOOK_TEXT}}
