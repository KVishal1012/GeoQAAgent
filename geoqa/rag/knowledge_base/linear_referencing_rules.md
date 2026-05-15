# Linear Referencing Rules Playbook

Use this playbook for route ID and measure issues.

Grounded guidance:
- Linear referencing workflows need route identifiers and valid from/to measures.
- Missing measures should be populated before dynamic segmentation or route-based analysis.
- Reversed measures should be corrected so `from_measure` is less than or equal to `to_measure`.
- Do not claim routing failure unless the QA evidence includes linear referencing issues or routing-specific checks.

