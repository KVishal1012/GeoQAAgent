from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "GeoQATitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#16221c"),
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "GeoQAHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#226b4f"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "GeoQABody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "GeoQASmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#627268"),
        spaceAfter=4,
    )
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.55 * inch,
        title="GeoQA Data Readiness Audit",
        author="GeoQA Agent",
    )
    story: list[Any] = []
    story.append(Paragraph("GeoQA Data Readiness Audit", title_style))
    story.append(Paragraph(f"{context['customer_name']} · {context['dataset_name']}", body_style))
    story.append(Paragraph(context['workflow_guidance']['decision'], heading_style))
    story.append(Paragraph(context['workflow_guidance']['rationale'], body_style))
    if context.get('decision_context'):
        story.append(Paragraph(f"Decision context: {context['decision_context']}", small_style))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Readiness Result", heading_style))
    summary_rows = [
        ["Readiness band", str(context['readiness_band'])],
        ["Readiness score", f"{context['readiness_score']}/100"],
        ["High findings", str(context['issue_counts']['high'])],
        ["Medium findings", str(context['issue_counts']['medium'])],
        ["Low findings", str(context['issue_counts']['low'])],
        ["Total findings", str(context['issue_counts']['total'])],
    ]
    summary_table = Table(summary_rows, colWidths=[1.8 * inch, 4.9 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#16221c")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7dfd8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dfd8")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Geometry Profile", heading_style))
    profile = context.get("geometry_profile") or {}
    story.append(Paragraph(f"Primary geometry: {profile.get('primary_geometry_label') or 'Unknown geometry'}", body_style))
    story.append(Paragraph(f"Technical geometry type: {profile.get('primary_geometry_type') or 'unknown'}", body_style))
    story.append(Paragraph(f"Curved, circular, or arc geometry detected: {profile.get('has_curves_or_arcs') or False}", body_style))
    story.append(Paragraph(f"Multipart geometry present: {profile.get('advanced_geometry_flags', {}).get('multi_part', False)}", body_style))
    story.append(Paragraph(f"Z coordinates present: {profile.get('has_z') or False}", body_style))

    if profile.get('observed_geometry_types'):
        geom_rows = [["Geometry type", "Plain-English label", "Count", "Share"]]
        for row in profile['observed_geometry_types']:
            geom_rows.append([row['type'], row['label'], str(row['count']), f"{row['percent']}%"])
        geom_table = Table(geom_rows, colWidths=[1.45 * inch, 2.35 * inch, 0.8 * inch, 0.8 * inch])
        geom_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7efe7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#16221c")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7dfd8")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dfd8")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("LEADING", (0, 0), (-1, -1), 10),
        ]))
        story.append(geom_table)
    if profile.get('notes'):
        for note in profile['notes']:
            story.append(Paragraph(note, small_style))

    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Spatial Anomalies", heading_style))
    anomalies = context.get("spatial_anomalies") or {}
    count = int(anomalies.get('count') or 0)
    if count:
        story.append(Paragraph(f"GeoQA flagged {count} spatial outlier feature{'s' if count != 1 else ''}.", body_style))
        if anomalies.get('feature_ids'):
            story.append(Paragraph(f"Flagged feature IDs: {', '.join(str(value) for value in anomalies['feature_ids'])}", small_style))
    else:
        story.append(Paragraph("No strong spatial outliers were detected by the configured anomaly check.", body_style))

    story.append(Paragraph("Critical Findings", heading_style))
    issues = context.get('top_issues') or []
    if issues:
        bullets = []
        for issue in issues[:10]:
            label = f"[{issue.get('severity', 'medium').title()}] {issue.get('issue_code')}"
            if issue.get('feature_id') is not None:
                label += f" for record {issue.get('feature_id')}"
            label += f": {issue.get('message')}"
            bullets.append(ListItem(Paragraph(label, body_style)))
        story.append(ListFlowable(bullets, bulletType='bullet'))
    else:
        story.append(Paragraph("No findings were detected by the configured checks.", body_style))

    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Recommended Next Steps", heading_style))
    next_steps = [
        "Review high-priority findings before loading or handoff.",
        "Confirm spatial anomalies with the source system of record.",
        "Use issues.csv for record-level triage and assignment.",
        "Keep the deterministic artifacts with the project audit trail.",
    ]
    story.append(ListFlowable([ListItem(Paragraph(item, body_style)) for item in next_steps], bulletType='bullet'))
    doc.build(story)
