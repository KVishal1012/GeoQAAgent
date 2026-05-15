from __future__ import annotations

import csv
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from geoqa.models import QAResult


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

    report_path = Path(artifacts["report"])
    report_path.write_text(_render_report(qa_result, template_dir), encoding="utf-8")

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
