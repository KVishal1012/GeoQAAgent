from __future__ import annotations

from typing import Any

from geoqa.config import AppConfig
from geoqa.llm.gateway import LLMGateway, build_openai_gateway
from geoqa.models import QAResult
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts, read_agent_review_status


def generate_bounded_report_draft(
    qa_result: QAResult,
    config: AppConfig,
    *,
    gateway: LLMGateway | None = None,
) -> dict[str, Any] | None:
    """Generate the reviewable report draft after deterministic QA has completed.

    Production environments without an enabled and fully configured provider keep
    the deterministic QA result, but do not claim that an agent draft exists.
    Tests and controlled runtimes can inject a gateway explicitly.
    """
    if not config.agent_report_enabled:
        return None
    selected_gateway = gateway
    if selected_gateway is None:
        if not config.openai_api_key or not config.llm_model:
            return None
        selected_gateway = build_openai_gateway(config)

    generate_agent_report_artifacts(
        qa_result,
        gateway=selected_gateway,
        model=config.llm_model,
        task="report",
        max_steps=config.agent_max_steps,
        runtime_config={
            "max_steps": config.agent_max_steps,
            "output_token_budget": config.agent_output_token_budget,
            "approval_required": True,
        },
    )
    return read_agent_review_status(qa_result.artifact_paths["output_dir"])
