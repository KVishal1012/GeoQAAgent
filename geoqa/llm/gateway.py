from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from geoqa.config import AppConfig


class LLMGatewayError(RuntimeError):
    """Raised when an LLM provider cannot produce a response."""

    def __init__(self, message: str, *, code: str = "gateway_error", transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMGateway(Protocol):
    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        """Generate a grounded report draft from a complete prompt."""


class OpenAILLMGateway:
    """OpenAI-first gateway with lazy imports so tests do not require the SDK."""

    provider = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        *,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        agent_report_enabled: bool = True,
        config: AppConfig | None = None,
    ) -> None:
        runtime_config = config
        self.api_key = api_key or (runtime_config.openai_api_key if runtime_config else os.getenv("OPENAI_API_KEY"))
        self.default_model = default_model or (runtime_config.llm_model if runtime_config else os.getenv("GEOQA_LLM_MODEL"))
        self.timeout_seconds = timeout_seconds or (runtime_config.openai_timeout_seconds if runtime_config else 30.0)
        self.max_retries = max_retries if max_retries is not None else (
            runtime_config.openai_max_retries if runtime_config else 2
        )
        self.retry_backoff_seconds = retry_backoff_seconds if retry_backoff_seconds is not None else (
            runtime_config.openai_retry_backoff_seconds if runtime_config else 1.0
        )
        self.agent_report_enabled = agent_report_enabled if runtime_config is None else runtime_config.agent_report_enabled

    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        selected_model = model or self.default_model
        if not self.agent_report_enabled:
            raise LLMGatewayError(
                "Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.",
                code="agent_reports_disabled",
            )
        if not selected_model:
            raise LLMGatewayError(
                "Set --llm-model or GEOQA_LLM_MODEL before generating an agent report.",
                code="missing_model",
            )
        if not self.api_key:
            raise LLMGatewayError(
                "Set OPENAI_API_KEY before generating an agent report.",
                code="missing_api_key",
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise LLMGatewayError(
                "Install the openai package to use the OpenAI gateway.",
                code="missing_openai_dependency",
            ) from exc

        client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        response = None
        last_error: LLMGatewayError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.responses.create(model=selected_model, input=prompt)
                break
            except Exception as exc:  # pragma: no cover - provider behavior
                last_error = _classify_openai_error(exc)
                if attempt >= self.max_retries or not last_error.transient:
                    raise last_error from exc
                time.sleep(self.retry_backoff_seconds * (attempt + 1))

        text = getattr(response, "output_text", None)
        if not text:
            text = _extract_response_text(response)
        if not text:
            raise LLMGatewayError("OpenAI response did not contain report text.", code="empty_response")
        return LLMResponse(
            text=text,
            model=selected_model,
            provider=self.provider,
            raw={
                "id": getattr(response, "id", None),
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "retry_backoff_seconds": self.retry_backoff_seconds,
            },
        )


class StaticLLMGateway:
    """Small fake gateway used by tests and local smoke checks."""

    provider = "static"

    def __init__(self, text: str, model: str = "static-test-model") -> None:
        self.text = text
        self.model = model

    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        return LLMResponse(
            text=self.text,
            model=model or self.model,
            provider=self.provider,
            raw={"prompt_length": len(prompt)},
        )


class StaticFileLLMGateway:
    """File-backed static gateway for demos and copy-paste CLI usage."""

    provider = "static"

    def __init__(self, report_path: str, model: str = "static-file-model") -> None:
        self.report_path = report_path
        self.model = model

    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        with open(self.report_path, encoding="utf-8") as handle:
            text = handle.read()
        return LLMResponse(
            text=text,
            model=model or self.model,
            provider=self.provider,
            raw={"prompt_length": len(prompt), "report_path": self.report_path},
        )


def _extract_response_text(response: Any) -> str:
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def build_openai_gateway(
    config: AppConfig,
    *,
    api_key: str | None = None,
    default_model: str | None = None,
) -> OpenAILLMGateway:
    effective_api_key = api_key or config.openai_api_key
    effective_model = default_model or config.llm_model
    if not config.agent_report_enabled:
        raise LLMGatewayError("Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.", code="agent_reports_disabled")
    if not effective_model:
        raise LLMGatewayError(
            "Set GEOQA_LLM_MODEL or pass --llm-model before generating an OpenAI agent report.",
            code="invalid_config",
        )
    if not effective_api_key:
        raise LLMGatewayError("Set OPENAI_API_KEY before generating an OpenAI agent report.", code="invalid_config")
    return OpenAILLMGateway(
        api_key=effective_api_key,
        default_model=effective_model,
        config=config,
    )


def _classify_openai_error(exc: Exception) -> LLMGatewayError:
    name = exc.__class__.__name__.lower()
    message = str(exc) or exc.__class__.__name__
    if "timeout" in name:
        return LLMGatewayError(f"OpenAI request timed out: {message}", code="timeout", transient=True)
    if "connection" in name or "apierror" in name or "rate" in name:
        return LLMGatewayError(f"OpenAI transient failure: {message}", code="transient_provider_error", transient=True)
    return LLMGatewayError(f"OpenAI report generation failed: {message}", code="provider_error")
