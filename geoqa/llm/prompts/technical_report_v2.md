Write a grounded GeoQA analyst report for task `{{TASK_NAME}}`.

You may use only:
- deterministic evidence in the JSON below
- tool outputs in the trace JSON below
- retrieved fix playbook text below

Rules:
- Every sentence must be grounded in the evidence or tool trace.
- Do not claim workflow unsuitability unless the evidence explicitly proves it.
- Use cautious language for downstream workflow guidance.
- Use plain-English labels suitable for non-GIS analysts.

Deterministic evidence:
{{EVIDENCE_JSON}}

Tool trace:
{{TOOL_TRACE_JSON}}

Retrieved playbooks:
{{PLAYBOOK_TEXT}}
