from __future__ import annotations

import json
from datetime import datetime, timezone
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
    comparison_key = str(summary["comparison_key"])
    storage_dir = comparison_dir / "comparisons" / comparison_key
    storage_dir.mkdir(parents=True, exist_ok=True)

    summary_path = storage_dir / "comparison_summary.json"
    report_path = storage_dir / "comparison_report.md"
    customer_report_path = storage_dir / "customer_comparison.md"
    latest_summary_path = comparison_dir / "comparison_summary.json"
    latest_report_path = comparison_dir / "comparison_report.md"
    index_path = comparison_dir / "comparison_index.json"

    summary_text = json.dumps(summary, indent=2)
    report_text = render_comparison_report(summary)
    customer_report_text = render_customer_comparison_report(summary)
    summary_path.write_text(summary_text, encoding="utf-8")
    report_path.write_text(report_text, encoding="utf-8")
    customer_report_path.write_text(customer_report_text, encoding="utf-8")
    latest_summary_path.write_text(summary_text, encoding="utf-8")
    latest_report_path.write_text(report_text, encoding="utf-8")
    _write_comparison_index(index_path, comparison_key, summary_path, report_path, summary)
    return {
        "comparison_key": comparison_key,
        "comparison_summary": str(summary_path),
        "comparison_report": str(report_path),
        "comparison_index": str(index_path),
        "customer_comparison": str(customer_report_path),
    }


def load_comparison_index(run_output_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_output_dir) / "comparison_index.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("comparisons", []))


def load_selected_comparison(run_output_dir: str | Path, comparison_key: str | None = None) -> dict[str, Any] | None:
    comparisons = load_comparison_index(run_output_dir)
    if not comparisons:
        return None
    if comparison_key:
        for comparison in comparisons:
            if comparison.get("comparison_key") == comparison_key:
                return _materialize_comparison(comparison)
        return None
    return _materialize_comparison(comparisons[0])


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
    base_run_id = str(base_evidence["run_record"].get("run_id", base_path.name))
    target_run_id = str(target_evidence["run_record"].get("run_id", target_path.name))
    generated_at = datetime.now(timezone.utc).isoformat()
    timestamp_key = generated_at.replace(":", "-").replace("+00:00", "Z")

    return {
        "comparison_key": f"against_{base_run_id}_{timestamp_key}",
        "generated_at": generated_at,
        "base_run_id": base_run_id,
        "target_run_id": target_run_id,
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
    new_types = [code.replace("_", " ").title() for code in summary["new_issue_codes"]]
    resolved_types = [code.replace("_", " ").title() for code in summary["resolved_issue_codes"]]
    lines = [
        "# GeoQA Change Report",
        "",
        f"Comparison reference: `{summary['comparison_key']}`",
        f"Baseline assessment folder: `{summary['base_run_dir']}`",
        f"Current assessment folder: `{summary['target_run_dir']}`",
        "",
        "## Readiness Changes",
        "",
        f"- Baseline readiness: `{summary['readiness_band_base']}`",
        f"- Current readiness: `{summary['readiness_band_target']}`",
        f"- Readiness score change: `{summary['readiness_score_delta']}`",
        "",
        "## Priority-Level Changes",
        "",
    ]
    for severity, delta in severity_deltas.items():
        lines.append(f"- `{severity.title()}`: `{delta}`")
    lines.extend(["", "## Finding Type Changes", ""])
    for code, delta in code_deltas.items():
        lines.append(f"- `{code.replace('_', ' ').title()}`: `{delta}`")
    lines.extend(
        [
            "",
            "## New Or Resolved Finding Types",
            "",
            f"- New finding types: {', '.join(f'`{value}`' for value in new_types) or 'none'}",
            f"- Resolved finding types: {', '.join(f'`{value}`' for value in resolved_types) or 'none'}",
        ]
    )
    return "\n".join(lines)


def _write_comparison_index(
    path: Path,
    comparison_key: str,
    summary_path: Path,
    report_path: Path,
    summary: dict[str, Any],
) -> None:
    comparisons = load_comparison_index(path.parent)
    entry = {
        "comparison_key": comparison_key,
        "generated_at": summary.get("generated_at"),
        "base_run_id": summary.get("base_run_id"),
        "target_run_id": summary.get("target_run_id"),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
    }
    comparisons = [item for item in comparisons if item.get("comparison_key") != comparison_key]
    comparisons.insert(0, entry)
    payload = {
        "latest_comparison_key": comparison_key,
        "comparisons": comparisons,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _materialize_comparison(index_entry: dict[str, Any]) -> dict[str, Any]:
    summary_path = Path(str(index_entry["summary_path"]))
    report_path = Path(str(index_entry["report_path"]))
    return {
        **index_entry,
        "summary": json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None,
        "report": report_path.read_text(encoding="utf-8") if report_path.exists() else None,
    }


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


def render_customer_comparison_report(summary: dict[str, Any]) -> str:
    from geoqa.reporting.customer_report import build_customer_comparison_context

    context = build_customer_comparison_context(summary)
    lines = [
        "# GeoQA Customer Comparison Brief",
        "",
        f"Baseline: `{context['base_label']}`",
        f"Current: `{context['target_label']}`",
        "",
        "## Summary",
        "",
        context['summary_line'],
        "",
        "## Readiness Change",
        "",
        f"- Baseline readiness: `{context['readiness_band_base']}`",
        f"- Current readiness: `{context['readiness_band_target']}`",
        f"- Readiness score change: `{context['readiness_score_delta']}`",
        "",
        "## Finding Changes",
        "",
    ]
    for severity, delta in context['severity_deltas'].items():
        lines.append(f"- `{severity.title()}` change: `{delta}`")
    lines.extend(["", "## New Finding Codes", ""])
    lines.append(", ".join(f"`{code}`" for code in context['new_issue_codes']) or "none")
    lines.extend(["", "## Resolved Finding Codes", ""])
    lines.append(", ".join(f"`{code}`" for code in context['resolved_issue_codes']) or "none")
    return "\n".join(lines)
