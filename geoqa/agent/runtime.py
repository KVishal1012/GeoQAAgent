from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geoqa.agent.tools import AgentToolCall, AgentToolError, invoke_agent_tool
from geoqa.llm.gateway import LLMGateway, OpenAILLMGateway, StaticLLMGateway
from geoqa.llm.prompt_registry import PromptRegistry
from geoqa.models import QAResult
from geoqa.rag.retriever import RetrievedPlaybook
from geoqa.reliability.hallucination_monitor import monitor_report_grounding
from geoqa.reliability.report_consistency import check_report_consistency
from geoqa.review.human_review import ReviewStatus, review_agent_report, write_review_status
from geoqa.reporting.agent_report_generator import load_evidence_bundle

TASK_PROMPTS = {
    "report": "technical_report_v2",
    "fix_plan": "fix_recommendation_v2",
    "handoff": "handoff_summary_v1",
}

DEFAULT_TOOL_PLANS = {
    "report": [
        ("load_run_evidence", "Load deterministic run evidence."),
        ("load_issue_summary", "Summarize findings by priority and finding type."),
        ("load_issue_rows_page", "Inspect a small slice of issue rows for examples."),
        ("retrieve_fix_playbooks", "Retrieve remediation guidance for the detected findings."),
    ],
    "fix_plan": [
        ("load_run_evidence", "Load deterministic run evidence."),
        ("load_issue_summary", "Summarize findings by priority and finding type."),
        ("retrieve_fix_playbooks", "Retrieve remediation guidance for the detected findings."),
        ("generate_fix_plan", "Generate the deterministic remediation plan artifacts."),
    ],
    "handoff": [
        ("load_run_evidence", "Load deterministic run evidence."),
        ("load_issue_summary", "Summarize findings by priority and finding type."),
        ("retrieve_fix_playbooks", "Retrieve remediation guidance for the detected findings."),
        ("generate_fix_plan", "Ensure remediation plan artifacts exist for the handoff."),
        ("load_comparison", "Load the selected comparison if one already exists."),
        ("export_handoff_bundle", "Build the downstream handoff bundle."),
    ],
}

ALLOWED_TOOLS = {task: [tool for tool, _ in steps] for task, steps in DEFAULT_TOOL_PLANS.items()}


@dataclass(slots=True)
class AgentSessionRecord:
    task: str
    model: str
    provider: str
    status: str
    started_at: str
    finished_at: str | None = None
    runtime_config: dict[str, Any] = field(default_factory=dict)
    step_count: int = 0
    planning_mode: str = "fallback"
    prompt_name: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_agent_task_artifacts(
    qa_result: QAResult,
    *,
    task: str = "report",
    gateway: LLMGateway | None = None,
    model: str | None = None,
    playbook_dir: str | Path | None = None,
    prompt_name: str | None = None,
    approve: bool = False,
    reviewer_name: str | None = None,
    review_notes: str | None = None,
    runtime_config: dict[str, Any] | None = None,
    max_steps: int | None = None,
    comparison_key: str | None = None,
    base_run_dir: str | Path | None = None,
) -> dict[str, str]:
    if task not in TASK_PROMPTS:
        raise AgentToolError(f"Unsupported agent task: {task}")

    output_dir = Path(qa_result.artifact_paths["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = load_evidence_bundle(output_dir)
    selected_gateway = gateway or OpenAILLMGateway(default_model=model)
    registry = PromptRegistry()
    selected_prompt = prompt_name or TASK_PROMPTS[task]
    planner_prompt = registry.render(
        "agent_planner_v1",
        {
            "TASK_NAME": task,
            "AVAILABLE_TOOLS_JSON": json.dumps(ALLOWED_TOOLS[task], indent=2),
            "EVIDENCE_JSON": json.dumps(
                {
                    "summary": evidence["summary"],
                    "run_record": evidence["run_record"],
                    "issue_summary": {"issue_count": len(evidence["issues"])},
                },
                indent=2,
                sort_keys=True,
            ),
        },
    )

    started_at = datetime.now(timezone.utc).isoformat()
    planning_mode = "fallback"
    planned_steps = DEFAULT_TOOL_PLANS[task]
    try:
        planner_response = selected_gateway.generate(planner_prompt, model=model)
        parsed_plan = _parse_planner_response(planner_response.text, task=task)
        if parsed_plan:
            planned_steps = parsed_plan
            planning_mode = "llm"
    except Exception:
        planner_response = None

    if max_steps is not None:
        planned_steps = planned_steps[:max_steps]

    tool_calls: list[AgentToolCall] = []
    for tool_name, reason in planned_steps:
        tool_calls.append(
            invoke_agent_tool(
                tool_name,
                output_dir=output_dir,
                playbook_dir=playbook_dir,
                comparison_key=comparison_key,
                base_run_dir=base_run_dir,
                reason=reason,
            )
        )

    report_prompt = registry.render(
        selected_prompt,
        {
            "TASK_NAME": task,
            "EVIDENCE_JSON": json.dumps(evidence, indent=2, sort_keys=True),
            "TOOL_TRACE_JSON": json.dumps([call.to_dict() for call in tool_calls], indent=2, sort_keys=True),
            "PLAYBOOK_TEXT": _extract_playbook_text(tool_calls),
        },
    )
    writer_response = selected_gateway.generate(report_prompt, model=model)

    draft_path = output_dir / "agent_report_draft.md"
    session_path = output_dir / "agent_session.json"
    trace_path = output_dir / "agent_trace.json"
    agent_json_path = output_dir / "agent_report.json"
    consistency_path = output_dir / "report_consistency.json"
    hallucination_path = output_dir / "hallucination_check.json"

    draft_path.write_text(writer_response.text, encoding="utf-8")

    playbook_payload = _extract_playbook_payload(tool_calls)
    consistency = check_report_consistency(
        writer_response.text,
        evidence["summary"],
        evidence["issues"],
        evidence["run_record"],
        agent_trace=[call.to_dict() for call in tool_calls],
    )
    consistency_path.write_text(json.dumps(consistency.to_dict(), indent=2), encoding="utf-8")

    hallucination = monitor_report_grounding(
        writer_response.text,
        evidence["summary"],
        evidence["issues"],
        evidence["run_record"],
        playbooks=playbook_payload,
        agent_trace=[call.to_dict() for call in tool_calls],
    )
    hallucination_path.write_text(json.dumps(hallucination.to_dict(), indent=2), encoding="utf-8")

    review = ReviewStatus(
        status="draft_ready" if consistency.passed and hallucination.passed else "blocked",
        draft_path=str(draft_path),
        blocking_errors=consistency.blocking_errors + hallucination.blocking_errors,
        warnings=consistency.warnings + hallucination.warnings,
    )
    write_review_status(output_dir, review)

    finished_at = datetime.now(timezone.utc).isoformat()
    session = AgentSessionRecord(
        task=task,
        model=writer_response.model,
        provider=writer_response.provider,
        status=review.status,
        started_at=started_at,
        finished_at=finished_at,
        runtime_config=runtime_config or {},
        step_count=len(tool_calls),
        planning_mode=planning_mode,
        prompt_name=selected_prompt,
        errors=list(review.blocking_errors),
    )
    session_path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    trace_path.write_text(
        json.dumps(
            {
                "task": task,
                "planning_mode": planning_mode,
                "planner_prompt": planner_prompt,
                "planner_raw": getattr(planner_response, "raw", {}) if planner_response else {},
                "tool_calls": [call.to_dict() for call in tool_calls],
                "writer_prompt": report_prompt,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    agent_json_payload = {
        "provider": writer_response.provider,
        "model": writer_response.model,
        "prompt_name": selected_prompt,
        "generated_at": finished_at,
        "task": task,
        "grounding_sources": ["summary.json", "issues.csv", "run_record.json"] + [item.get("source") for item in playbook_payload],
        "runtime_config": runtime_config or {},
        "playbooks": playbook_payload,
        "report_text": writer_response.text,
        "raw": writer_response.raw,
        "consistency": consistency.to_dict(),
        "hallucination": hallucination.to_dict(),
        "review_status": review.to_dict(),
        "agent_session": session.to_dict(),
        "agent_session_path": str(session_path),
        "agent_trace_path": str(trace_path),
    }
    agent_json_path.write_text(json.dumps(agent_json_payload, indent=2), encoding="utf-8")

    artifacts = {
        "agent_report_draft": str(draft_path),
        "agent_report_json": str(agent_json_path),
        "report_consistency": str(consistency_path),
        "hallucination_check": str(hallucination_path),
        "review_status": str(output_dir / "review_status.json"),
        "review_history": str(output_dir / "review_history.jsonl"),
        "agent_session": str(session_path),
        "agent_trace": str(trace_path),
    }
    if approve:
        approved = review_agent_report(output_dir, action="approve", reviewer_name=reviewer_name or "", notes=review_notes)
        _update_agent_json_review_status(agent_json_path, approved)
        artifacts["agent_report"] = str(approved.final_path)
    return artifacts


def _parse_planner_response(planner_text: str, *, task: str) -> list[tuple[str, str]] | None:
    payload = _extract_json_object(planner_text)
    if not payload:
        return None
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return None
    allowed = set(ALLOWED_TOOLS[task])
    parsed: list[tuple[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        tool_name = str(step.get("tool", ""))
        if tool_name not in allowed:
            continue
        parsed.append((tool_name, str(step.get("reason", "LLM planned step."))))
    return parsed or None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _extract_playbook_payload(tool_calls: list[AgentToolCall]) -> list[dict[str, Any]]:
    for call in tool_calls:
        playbooks = call.output_summary.get("playbooks")
        if isinstance(playbooks, dict):
            preview = playbooks.get("preview", [])
            if isinstance(preview, list):
                return [item for item in preview if isinstance(item, dict)]
    return []


def _extract_playbook_text(tool_calls: list[AgentToolCall]) -> str:
    payload = _extract_playbook_payload(tool_calls)
    if not payload:
        return "No fix playbooks were retrieved for this run."
    chunks: list[str] = []
    for playbook in payload:
        text = playbook.get("text")
        if text:
            chunks.append(str(text))
    return "\n\n".join(chunks) if chunks else "No fix playbooks were retrieved for this run."


def _update_agent_json_review_status(agent_json_path: Path, status: ReviewStatus) -> None:
    if not agent_json_path.exists():
        return
    payload = json.loads(agent_json_path.read_text(encoding="utf-8"))
    payload["review_status"] = status.to_dict()
    agent_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class StaticAgentSessionRunner:
    def __init__(self, report_text: str, model: str = "static-agent-model") -> None:
        self.gateway = StaticLLMGateway(report_text, model=model)

    def run(self, qa_result: QAResult, **kwargs: Any) -> dict[str, str]:
        return run_agent_task_artifacts(qa_result, gateway=self.gateway, **kwargs)
