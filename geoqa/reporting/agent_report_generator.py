from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from geoqa.llm.gateway import LLMGateway
from geoqa.models import QAResult
from geoqa.review.human_review import ReviewStatus, read_review_status, review_agent_report


def generate_agent_report_artifacts(
    qa_result: QAResult,
    gateway: LLMGateway | None = None,
    model: str | None = None,
    playbook_dir: str | Path | None = None,
    prompt_name: str = "technical_report_v2",
    approve: bool = False,
    reviewer_name: str | None = None,
    review_notes: str | None = None,
    runtime_config: dict[str, Any] | None = None,
    task: str = "report",
    max_steps: int | None = None,
    comparison_key: str | None = None,
    base_run_dir: str | Path | None = None,
) -> dict[str, str]:
    from geoqa.agent.runtime import run_agent_task_artifacts

    return run_agent_task_artifacts(
        qa_result,
        task=task,
        gateway=gateway,
        model=model,
        playbook_dir=playbook_dir,
        prompt_name=prompt_name,
        approve=approve,
        reviewer_name=reviewer_name,
        review_notes=review_notes,
        runtime_config=runtime_config,
        max_steps=max_steps,
        comparison_key=comparison_key,
        base_run_dir=base_run_dir,
    )


def load_evidence_bundle(output_dir: str | Path) -> dict[str, Any]:
    output_path = Path(output_dir)
    summary = _read_json(output_path / "summary.json")
    run_record = _read_json(output_path / "run_record.json")
    issues = _read_issues(output_path / "issues.csv")
    return {"summary": summary, "issues": issues, "run_record": run_record}


def review_existing_agent_report(
    output_dir: str | Path,
    action: str,
    reviewer_name: str,
    notes: str | None = None,
) -> dict[str, str | None]:
    output_path = Path(output_dir)
    status = review_agent_report(output_dir, action=action, reviewer_name=reviewer_name, notes=notes)
    _update_agent_json_review_status(output_dir, status)
    return {
        "agent_report": str(status.final_path) if status.final_path else None,
        "review_status": str(output_path / "review_status.json"),
        "review_history": str(output_path / "review_history.jsonl"),
    }


def read_agent_review_status(output_dir: str | Path) -> dict[str, Any] | None:
    status = read_review_status(output_dir)
    if status is None:
        return None
    return status.to_dict()


def _update_agent_json_review_status(output_dir: str | Path, status: ReviewStatus) -> None:
    agent_json_path = Path(output_dir) / "agent_report.json"
    if not agent_json_path.exists():
        return
    payload = json.loads(agent_json_path.read_text(encoding="utf-8"))
    payload["review_status"] = status.to_dict()
    agent_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_issues(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        context = row.get("context")
        if context:
            try:
                row["context"] = json.loads(context)
            except json.JSONDecodeError:
                row["context"] = context
    return rows
