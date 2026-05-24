from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from geoqa.rag.retriever import retrieve_playbooks
from geoqa.reporting.agent_report_generator import load_evidence_bundle
from geoqa.workflows import (
    compare_run_outputs,
    export_handoff_bundle,
    generate_fix_plan_artifacts,
    load_comparison_index,
    load_run_index,
    load_selected_comparison,
)


class AgentToolError(RuntimeError):
    """Raised when an internal GeoQA agent tool cannot complete."""


@dataclass(slots=True)
class AgentToolCall:
    name: str
    reason: str
    input_payload: dict[str, Any]
    output_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_run_evidence(output_dir: str | Path) -> dict[str, Any]:
    evidence = load_evidence_bundle(output_dir)
    return {
        "summary": evidence["summary"],
        "run_record": evidence["run_record"],
        "issue_count": len(evidence["issues"]),
    }


def load_issue_summary(output_dir: str | Path) -> dict[str, Any]:
    evidence = load_evidence_bundle(output_dir)
    issue_counts_by_code: dict[str, int] = {}
    severity_counts = {"high": 0, "medium": 0, "low": 0, "total": len(evidence["issues"])}
    for issue in evidence["issues"]:
        code = str(issue.get("issue_code", ""))
        if code:
            issue_counts_by_code[code] = issue_counts_by_code.get(code, 0) + 1
        severity = str(issue.get("severity", ""))
        if severity in severity_counts:
            severity_counts[severity] += 1
    top_issues = []
    for issue in evidence["issues"][:10]:
        top_issues.append(
            {
                "issue_code": issue.get("issue_code"),
                "severity": issue.get("severity"),
                "feature_id": issue.get("feature_id"),
                "message": issue.get("message"),
                "suggested_fix": issue.get("suggested_fix"),
            }
        )
    return {
        "severity_counts": severity_counts,
        "issue_counts_by_code": dict(sorted(issue_counts_by_code.items())),
        "top_issues": top_issues,
    }


def load_issue_rows_page(
    output_dir: str | Path,
    *,
    severity: str | None = None,
    issue_code: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    evidence = load_evidence_bundle(output_dir)
    filtered = [
        issue
        for issue in evidence["issues"]
        if (not severity or issue.get("severity") == severity)
        and (not issue_code or issue.get("issue_code") == issue_code)
    ]
    return {
        "total_rows": len(filtered),
        "offset": offset,
        "limit": limit,
        "rows": filtered[offset : offset + limit],
    }


def load_recent_runs(output_dir: str | Path) -> list[dict[str, Any]]:
    return load_run_index(Path(output_dir).parent)


def load_comparison(output_dir: str | Path, comparison_key: str | None = None) -> dict[str, Any] | None:
    return load_selected_comparison(output_dir, comparison_key=comparison_key)


def retrieve_fix_playbooks_for_run(output_dir: str | Path, playbook_dir: str | Path | None = None) -> list[dict[str, Any]]:
    evidence = load_evidence_bundle(output_dir)
    return [playbook.to_dict() for playbook in retrieve_playbooks(evidence["issues"], playbook_dir=playbook_dir)]


def generate_fix_plan(output_dir: str | Path, playbook_dir: str | Path | None = None) -> dict[str, Any]:
    artifacts = generate_fix_plan_artifacts(output_dir, playbook_dir=playbook_dir)
    fix_plan_json = Path(artifacts["fix_plan_json"])
    payload = json.loads(fix_plan_json.read_text(encoding="utf-8")) if fix_plan_json.exists() else {}
    return {"artifacts": artifacts, "summary": payload}


def generate_comparison(
    output_dir: str | Path,
    *,
    base_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not base_run_dir:
        raise AgentToolError("generate_comparison requires a base_run_dir.")
    artifacts = compare_run_outputs(base_run_dir, output_dir)
    summary_path = Path(artifacts["comparison_summary"])
    payload = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    return {"artifacts": artifacts, "summary": payload}


def export_handoff(
    output_dir: str | Path,
    *,
    comparison_key: str | None = None,
) -> dict[str, Any]:
    artifacts = export_handoff_bundle(output_dir, comparison_key=comparison_key)
    manifest_path = Path(artifacts["bundle_manifest"])
    payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return {"artifacts": artifacts, "manifest": payload}


def invoke_agent_tool(
    tool_name: str,
    *,
    output_dir: str | Path,
    playbook_dir: str | Path | None = None,
    comparison_key: str | None = None,
    base_run_dir: str | Path | None = None,
    reason: str = "",
) -> AgentToolCall:
    if tool_name == "load_run_evidence":
        output = load_run_evidence(output_dir)
    elif tool_name == "load_issue_summary":
        output = load_issue_summary(output_dir)
    elif tool_name == "load_issue_rows_page":
        output = load_issue_rows_page(output_dir)
    elif tool_name == "load_recent_runs":
        output = {"recent_runs": load_recent_runs(output_dir)[:10]}
    elif tool_name == "load_comparison":
        output = {"comparison": load_comparison(output_dir, comparison_key=comparison_key)}
    elif tool_name == "retrieve_fix_playbooks":
        output = {"playbooks": retrieve_fix_playbooks_for_run(output_dir, playbook_dir=playbook_dir)}
    elif tool_name == "generate_fix_plan":
        output = generate_fix_plan(output_dir, playbook_dir=playbook_dir)
    elif tool_name == "generate_comparison":
        output = generate_comparison(output_dir, base_run_dir=base_run_dir)
    elif tool_name == "export_handoff_bundle":
        output = export_handoff(output_dir, comparison_key=comparison_key)
    else:
        raise AgentToolError(f"Unsupported tool: {tool_name}")

    return AgentToolCall(
        name=tool_name,
        reason=reason,
        input_payload={
            "output_dir": str(output_dir),
            "playbook_dir": str(playbook_dir) if playbook_dir else None,
            "comparison_key": comparison_key,
            "base_run_dir": str(base_run_dir) if base_run_dir else None,
        },
        output_summary=_summarize_output(output),
    )


def _summarize_output(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        summary: dict[str, Any] = {}
        for key, value in output.items():
            if isinstance(value, list):
                summary[key] = {"count": len(value), "preview": value[:3]}
            elif isinstance(value, dict):
                summary[key] = value
            else:
                summary[key] = value
        return summary
    return {"value": output}
