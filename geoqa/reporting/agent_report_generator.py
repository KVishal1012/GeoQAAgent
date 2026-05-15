from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from geoqa.llm.gateway import LLMGateway, LLMResponse, OpenAILLMGateway
from geoqa.llm.prompt_registry import PromptRegistry
from geoqa.models import QAResult
from geoqa.rag.retriever import RetrievedPlaybook, render_playbooks, retrieve_playbooks
from geoqa.reliability.hallucination_monitor import monitor_report_grounding
from geoqa.reliability.report_consistency import check_report_consistency
from geoqa.review.human_review import ReviewStatus, approve_agent_report, write_review_status


def generate_agent_report_artifacts(
    qa_result: QAResult,
    gateway: LLMGateway | None = None,
    model: str | None = None,
    playbook_dir: str | Path | None = None,
    prompt_name: str = "technical_report_v1",
    approve: bool = False,
    reviewer_name: str | None = None,
) -> dict[str, str]:
    output_dir = Path(qa_result.artifact_paths["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = load_evidence_bundle(output_dir)
    playbooks = retrieve_playbooks(evidence["issues"], playbook_dir=playbook_dir)
    prompt = build_agent_prompt(evidence, playbooks, prompt_name=prompt_name)
    selected_gateway = gateway or OpenAILLMGateway(default_model=model)
    llm_response = selected_gateway.generate(prompt, model=model)

    draft_path = output_dir / "agent_report_draft.md"
    agent_json_path = output_dir / "agent_report.json"
    consistency_path = output_dir / "report_consistency.json"
    hallucination_path = output_dir / "hallucination_check.json"

    draft_path.write_text(llm_response.text, encoding="utf-8")
    playbook_payload = [playbook.to_dict() for playbook in playbooks]
    agent_json_path.write_text(
        json.dumps(
            {
                "provider": llm_response.provider,
                "model": llm_response.model,
                "prompt_name": prompt_name,
                "grounding_sources": ["summary.json", "issues.csv", "run_record.json"]
                + [playbook.source for playbook in playbooks],
                "playbooks": playbook_payload,
                "report_text": llm_response.text,
                "raw": llm_response.raw,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    consistency = check_report_consistency(
        llm_response.text,
        evidence["summary"],
        evidence["issues"],
        evidence["run_record"],
    )
    consistency_path.write_text(json.dumps(consistency.to_dict(), indent=2), encoding="utf-8")

    hallucination = monitor_report_grounding(
        llm_response.text,
        evidence["summary"],
        evidence["issues"],
        evidence["run_record"],
        playbooks=playbook_payload,
    )
    hallucination_path.write_text(json.dumps(hallucination.to_dict(), indent=2), encoding="utf-8")

    review = ReviewStatus(
        status="draft_ready" if consistency.passed and hallucination.passed else "blocked",
        draft_path=str(draft_path),
        blocking_errors=consistency.blocking_errors + hallucination.blocking_errors,
        warnings=consistency.warnings + hallucination.warnings,
    )
    write_review_status(output_dir, review)

    artifacts = {
        "agent_report_draft": str(draft_path),
        "agent_report_json": str(agent_json_path),
        "report_consistency": str(consistency_path),
        "hallucination_check": str(hallucination_path),
        "review_status": str(output_dir / "review_status.json"),
    }
    if approve:
        approved = approve_agent_report(output_dir, reviewer_name or "")
        artifacts["agent_report"] = str(approved.final_path)
    return artifacts


def build_agent_prompt(
    evidence: dict[str, Any],
    playbooks: list[RetrievedPlaybook],
    prompt_name: str = "technical_report_v1",
    registry: PromptRegistry | None = None,
) -> str:
    prompt_registry = registry or PromptRegistry()
    evidence_json = json.dumps(
        {
            "summary": evidence["summary"],
            "issues": evidence["issues"],
            "run_record": evidence["run_record"],
        },
        indent=2,
        sort_keys=True,
    )
    return prompt_registry.render(
        prompt_name,
        {
            "EVIDENCE_JSON": evidence_json,
            "PLAYBOOK_TEXT": render_playbooks(playbooks),
        },
    )


def load_evidence_bundle(output_dir: str | Path) -> dict[str, Any]:
    output_path = Path(output_dir)
    summary = _read_json(output_path / "summary.json")
    run_record = _read_json(output_path / "run_record.json")
    issues = _read_issues(output_path / "issues.csv")
    return {"summary": summary, "issues": issues, "run_record": run_record}


def approve_existing_agent_report(output_dir: str | Path, reviewer_name: str, notes: str | None = None) -> dict[str, str]:
    status = approve_agent_report(output_dir, reviewer_name=reviewer_name, notes=notes)
    return {"agent_report": str(status.final_path), "review_status": str(Path(output_dir) / "review_status.json")}


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

