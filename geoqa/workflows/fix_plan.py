from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geoqa.rag.retriever import render_playbooks, retrieve_playbooks
from geoqa.reporting.agent_report_generator import load_evidence_bundle


def generate_fix_plan_artifacts(run_output_dir: str | Path) -> dict[str, str]:
    output_path = Path(run_output_dir)
    evidence = load_evidence_bundle(output_path)
    playbooks = retrieve_playbooks(evidence["issues"])
    plan = build_fix_plan(evidence, [playbook.to_dict() for playbook in playbooks])
    markdown = render_fix_plan_markdown(plan)

    json_path = output_path / "fix_plan.json"
    markdown_path = output_path / "fix_plan.md"
    json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    return {
        "fix_plan_json": str(json_path),
        "fix_plan_markdown": str(markdown_path),
    }


def build_fix_plan(evidence: dict[str, Any], playbooks: list[dict[str, Any]]) -> dict[str, Any]:
    issue_groups: dict[str, dict[str, Any]] = {}
    for issue in evidence["issues"]:
        code = str(issue.get("issue_code", ""))
        group = issue_groups.setdefault(
            code,
            {
                "issue_code": code,
                "severity": issue.get("severity"),
                "count": 0,
                "feature_ids": [],
                "columns": [],
                "messages": [],
                "suggested_fix": issue.get("suggested_fix"),
            },
        )
        group["count"] += 1
        if issue.get("feature_id") not in (None, ""):
            group["feature_ids"].append(issue["feature_id"])
        context = issue.get("context")
        if isinstance(context, dict) and context.get("column"):
            group["columns"].append(context["column"])
        if issue.get("message"):
            group["messages"].append(issue["message"])

    playbook_map = {code: [] for code in issue_groups}
    for playbook in playbooks:
        for code in playbook.get("issue_codes", []):
            if code in playbook_map:
                playbook_map[code].append(
                    {
                        "title": playbook.get("title"),
                        "source": playbook.get("source"),
                        "text": playbook.get("text"),
                    }
                )

    groups = []
    for code, group in sorted(issue_groups.items()):
        groups.append(
            {
                **group,
                "feature_ids": sorted({str(value) for value in group["feature_ids"]}),
                "columns": sorted({str(value) for value in group["columns"]}),
                "messages": group["messages"][:5],
                "playbooks": playbook_map.get(code, []),
            }
        )

    return {
        "dataset": evidence["summary"].get("dataset", {}),
        "prompt_template_name": "fix_recommendation_v1",
        "playbook_sources": [playbook.get("source") for playbook in playbooks],
        "issue_groups": groups,
    }


def render_fix_plan_markdown(plan: dict[str, Any]) -> str:
    dataset = plan.get("dataset", {})
    lines = [
        "# GeoQA Fix Plan",
        "",
        f"Dataset: `{dataset.get('filename', 'dataset')}`",
        "",
        f"Prompt template surfaced for this workflow: `{plan.get('prompt_template_name')}`",
        "",
    ]
    for group in plan.get("issue_groups", []):
        lines.extend(
            [
                f"## `{group['issue_code']}`",
                "",
                f"- Severity: `{group['severity']}`",
                f"- Count: `{group['count']}`",
                f"- Suggested action: {group['suggested_fix']}",
            ]
        )
        if group["feature_ids"]:
            lines.append(f"- Affected feature IDs: {', '.join(f'`{value}`' for value in group['feature_ids'])}")
        if group["columns"]:
            lines.append(f"- Affected columns: {', '.join(f'`{value}`' for value in group['columns'])}")
        if group["messages"]:
            lines.append(f"- Example finding: {group['messages'][0]}")
        if group["playbooks"]:
            lines.append(
                "- Relevant playbooks: "
                + ", ".join(f"`{playbook['title']}`" for playbook in group["playbooks"])
            )
        lines.append("")
    return "\n".join(lines)
