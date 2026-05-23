from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geoqa.reporting.agent_report_generator import load_evidence_bundle


def compare_run_outputs(
    base_run_dir: str | Path,
    target_run_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, str]:
    base_path = Path(base_run_dir)
    target_path = Path(target_run_dir)
    base_evidence = load_evidence_bundle(base_path)
    target_evidence = load_evidence_bundle(target_path)
    comparison_dir = Path(output_dir) if output_dir else target_path
    comparison_dir.mkdir(parents=True, exist_ok=True)

    summary = build_comparison_summary(base_evidence, target_evidence, base_path=base_path, target_path=target_path)
    summary_path = comparison_dir / "comparison_summary.json"
    report_path = comparison_dir / "comparison_report.md"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_path.write_text(render_comparison_report(summary), encoding="utf-8")
    return {
        "comparison_summary": str(summary_path),
        "comparison_report": str(report_path),
    }


def build_comparison_summary(
    base_evidence: dict[str, Any],
    target_evidence: dict[str, Any],
    *,
    base_path: Path,
    target_path: Path,
) -> dict[str, Any]:
    base_readiness = base_evidence["summary"].get("readiness", {})
    target_readiness = target_evidence["summary"].get("readiness", {})
    base_issue_counts = _severity_counts(base_evidence["issues"])
    target_issue_counts = _severity_counts(target_evidence["issues"])
    base_issue_code_counts = _issue_code_counts(base_evidence["issues"])
    target_issue_code_counts = _issue_code_counts(target_evidence["issues"])
    base_codes = set(base_issue_code_counts)
    target_codes = set(target_issue_code_counts)

    return {
        "base_run_dir": str(base_path),
        "target_run_dir": str(target_path),
        "dataset_name": target_evidence["summary"].get("dataset", {}).get("filename"),
        "readiness_score_delta": int(target_readiness.get("score", 0)) - int(base_readiness.get("score", 0)),
        "readiness_band_base": base_readiness.get("band"),
        "readiness_band_target": target_readiness.get("band"),
        "issue_count_deltas_by_severity": {
            severity: target_issue_counts.get(severity, 0) - base_issue_counts.get(severity, 0)
            for severity in ("high", "medium", "low", "total")
        },
        "issue_count_deltas_by_issue_code": {
            code: target_issue_code_counts.get(code, 0) - base_issue_code_counts.get(code, 0)
            for code in sorted(base_codes | target_codes)
        },
        "new_issue_codes": sorted(target_codes - base_codes),
        "resolved_issue_codes": sorted(base_codes - target_codes),
    }


def render_comparison_report(summary: dict[str, Any]) -> str:
    severity_deltas = summary["issue_count_deltas_by_severity"]
    code_deltas = summary["issue_count_deltas_by_issue_code"]
    lines = [
        "# GeoQA Run Comparison Report",
        "",
        f"Base run: `{summary['base_run_dir']}`",
        f"Target run: `{summary['target_run_dir']}`",
        "",
        "## Readiness Changes",
        "",
        f"- Base readiness band: `{summary['readiness_band_base']}`",
        f"- Target readiness band: `{summary['readiness_band_target']}`",
        f"- Readiness score delta: `{summary['readiness_score_delta']}`",
        "",
        "## Severity Deltas",
        "",
    ]
    for severity, delta in severity_deltas.items():
        lines.append(f"- `{severity}`: `{delta}`")
    lines.extend(["", "## Issue Code Deltas", ""])
    for code, delta in code_deltas.items():
        lines.append(f"- `{code}`: `{delta}`")
    lines.extend(
        [
            "",
            "## Issue Code Changes",
            "",
            f"- New issue codes: {', '.join(f'`{code}`' for code in summary['new_issue_codes']) or 'none'}",
            f"- Resolved issue codes: {', '.join(f'`{code}`' for code in summary['resolved_issue_codes']) or 'none'}",
        ]
    )
    return "\n".join(lines)


def _severity_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "total": len(issues)}
    for issue in issues:
        severity = str(issue.get("severity", ""))
        if severity in counts:
            counts[severity] += 1
    return counts


def _issue_code_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        code = str(issue.get("issue_code", ""))
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts
