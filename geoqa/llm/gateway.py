from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMGatewayError(RuntimeError):
    """Raised when an LLM provider cannot produce a response."""


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

    def __init__(self, api_key: str | None = None, default_model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.default_model = default_model or os.getenv("GEOQA_LLM_MODEL")

    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        selected_model = model or self.default_model
        if not selected_model:
            raise LLMGatewayError("Set --llm-model or GEOQA_LLM_MODEL before generating an agent report.")
        if not self.api_key:
            raise LLMGatewayError("Set OPENAI_API_KEY before generating an agent report.")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise LLMGatewayError("Install the openai package to use the OpenAI gateway.") from exc

        client = OpenAI(api_key=self.api_key)
        try:
            response = client.responses.create(model=selected_model, input=prompt)
        except Exception as exc:  # pragma: no cover - provider behavior
            raise LLMGatewayError(f"OpenAI report generation failed: {exc}") from exc

        text = getattr(response, "output_text", None)
        if not text:
            text = _extract_response_text(response)
        if not text:
            raise LLMGatewayError("OpenAI response did not contain report text.")
        return LLMResponse(
            text=text,
            model=selected_model,
            provider=self.provider,
            raw={"id": getattr(response, "id", None)},
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
