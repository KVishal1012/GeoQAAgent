from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from geoqa.models import QAResult
from geoqa.reporting.customer_report import build_customer_report_context
from geoqa.workflows.run_index import append_run_index


def generate_artifacts(
    qa_result: QAResult,
    output_root: str | Path,
    template_dir: str | Path | None = None,
) -> dict[str, str]:
    output_dir = Path(output_root) / qa_result.run_record.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "output_dir": str(output_dir),
        "issues_csv": str(output_dir / "issues.csv"),
        "run_record": str(output_dir / "run_record.json"),
        "summary": str(output_dir / "summary.json"),
        "geometry_profile": str(output_dir / "geometry_profile.json"),
        "customer_intake": str(output_dir / "customer_intake.json"),
        "customer_report": str(output_dir / "customer_report.md"),
        "customer_report_pdf": str(output_dir / "customer_report.pdf"),
        "report": str(output_dir / "qa_report.md"),
    }
    qa_result.artifact_paths = artifacts

    csv_path = Path(artifacts["issues_csv"])
    _write_issues_csv(csv_path, qa_result)

    run_record_path = Path(artifacts["run_record"])
    run_record_path.write_text(
        json.dumps(qa_result.run_record.to_dict(), indent=2),
        encoding="utf-8",
    )

    summary_path = Path(artifacts["summary"])
    summary_path.write_text(json.dumps(qa_result.summary, indent=2), encoding="utf-8")

    geometry_profile_path = Path(artifacts["geometry_profile"])
    geometry_profile_path.write_text(
        json.dumps(qa_result.summary.get("dataset", {}).get("geometry_profile", {}), indent=2),
        encoding="utf-8",
    )

    customer_intake_path = Path(artifacts["customer_intake"])
    customer_intake_path.write_text(
        json.dumps(qa_result.summary.get("customer_intake", {}), indent=2),
        encoding="utf-8",
    )

    report_path = Path(artifacts["report"])
    report_path.write_text(_render_report(qa_result, template_dir), encoding="utf-8")

    customer_report_path = Path(artifacts["customer_report"])
    customer_report_text = _render_customer_report(qa_result, template_dir)
    customer_report_path.write_text(customer_report_text, encoding="utf-8")

    customer_report_pdf_path = Path(artifacts["customer_report_pdf"])
    _write_customer_report_pdf(customer_report_pdf_path, build_customer_report_context(qa_result))
    append_run_index(qa_result, output_root)

    return artifacts


def _write_issues_csv(path: Path, qa_result: QAResult) -> None:
    rows = [issue.to_dict() for issue in qa_result.issues]
    fieldnames = [
        "issue_code",
        "check_name",
        "severity",
        "feature_id",
        "message",
        "suggested_fix",
        "context",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row["context"] = json.dumps(row.get("context", {}), sort_keys=True)
            writer.writerow(row)


def _render_report(qa_result: QAResult, template_dir: str | Path | None) -> str:
    base_dir = Path(template_dir) if template_dir else Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(base_dir)),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("qa_report.md.j2")
    return template.render(result=qa_result.to_dict())


def _render_customer_report(qa_result: QAResult, template_dir: str | Path | None) -> str:
    base_dir = Path(template_dir) if template_dir else Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(base_dir)),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("customer_report.md.j2")
    return template.render(context=build_customer_report_context(qa_result))


def _write_customer_report_pdf(path: Path, context: dict[str, Any]) -> None:
    lines = [
        "GeoQA Data Readiness Audit",
        f"{context['customer_name']} - {context['dataset_name']}",
        "",
        context['workflow_guidance']['decision'],
        context['workflow_guidance']['rationale'],
        "",
        "Readiness Result",
        f"Readiness band: {context['readiness_band']}",
        f"Readiness score: {context['readiness_score']}/100",
        f"High findings: {context['issue_counts']['high']}",
        f"Medium findings: {context['issue_counts']['medium']}",
        f"Low findings: {context['issue_counts']['low']}",
        f"Total findings: {context['issue_counts']['total']}",
        "",
        "Geometry Profile",
        f"Primary geometry: {context.get('geometry_profile', {}).get('primary_geometry_label') or 'Unknown geometry'}",
        f"Technical geometry type: {context.get('geometry_profile', {}).get('primary_geometry_type') or 'unknown'}",
        f"Curved, circular, or arc geometry detected: {context.get('geometry_profile', {}).get('has_curves_or_arcs') or False}",
        f"Multipart geometry present: {context.get('geometry_profile', {}).get('advanced_geometry_flags', {}).get('multi_part', False)}",
        f"Z coordinates present: {context.get('geometry_profile', {}).get('has_z') or False}",
    ]
    if context.get('decision_context'):
        lines.extend(["", f"Decision context: {context['decision_context']}"])
    profile = context.get('geometry_profile') or {}
    if profile.get('notes'):
        lines.extend(["", "Geometry notes:"] + [f"- {note}" for note in profile['notes']])
    anomalies = context.get('spatial_anomalies') or {}
    lines.extend(["", "Spatial Anomalies"])
    count = int(anomalies.get('count') or 0)
    if count:
        lines.append(f"GeoQA flagged {count} spatial outlier feature{'s' if count != 1 else ''}.")
        if anomalies.get('feature_ids'):
            lines.append(f"Flagged feature IDs: {', '.join(str(value) for value in anomalies['feature_ids'])}")
    else:
        lines.append("No strong spatial outliers were detected by the configured anomaly check.")
    lines.extend(["", "Critical Findings"])
    issues = context.get('top_issues') or []
    if issues:
        for issue in issues[:6]:
            lines.append(f"- {issue.get('severity', 'unknown').title()} | {issue.get('issue_code', 'ISSUE')} | {issue.get('message', '')}")
    else:
        lines.append("No critical issues were identified in the first-pass summary.")
    lines.extend(["", "Next Steps"])
    for step in context.get('next_steps', [])[:4]:
        lines.append(f"- {step}")
    _write_simple_pdf(path, lines)



def _write_simple_pdf(path: Path, lines: list[str]) -> None:
    def esc(text: str) -> str:
        return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    content_lines = ["BT", "/F1 12 Tf", "72 740 Td"]
    first = True
    for line in lines:
        safe = esc(str(line))
        if first:
            content_lines.append(f"({safe}) Tj")
            first = False
        else:
            content_lines.append("0 -16 Td")
            content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("utf-8")
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("utf-8") + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("utf-8"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("utf-8"))
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("utf-8"))
    path.write_bytes(pdf)
