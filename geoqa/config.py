from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class AppConfig:
    openai_api_key: str | None
    llm_model: str | None
    output_root: str
    agent_report_enabled: bool
    openai_timeout_seconds: float
    openai_max_retries: int
    openai_retry_backoff_seconds: float
    agent_max_steps: int
    agent_output_token_budget: int
    env_file: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["openai_api_key"] = "***configured***" if self.openai_api_key else None
        return payload

    def validate_for_agent_provider(self, provider: str) -> None:
        if provider == "openai":
            if not self.agent_report_enabled:
                raise ConfigError("Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.")
            if not self.llm_model:
                raise ConfigError("Set GEOQA_LLM_MODEL or pass --llm-model before generating an OpenAI agent report.")
            if not self.openai_api_key:
                raise ConfigError("Set OPENAI_API_KEY before generating an OpenAI agent report.")


def load_app_config(env_file: str | None = None) -> AppConfig:
    env_values = dict(os.environ)
    resolved_env, file_values = _load_env_file(env_file)
    for key, value in file_values.items():
        env_values.setdefault(key, value)

    output_root = env_values.get("GEOQA_OUTPUT_ROOT", "outputs").strip() or "outputs"
    agent_report_enabled = _parse_bool(env_values.get("GEOQA_AGENT_REPORT_ENABLED"), default=True)
    openai_timeout_seconds = _parse_float(
        env_values.get("GEOQA_OPENAI_TIMEOUT_SECONDS"),
        name="GEOQA_OPENAI_TIMEOUT_SECONDS",
        default=30.0,
        minimum=1.0,
    )
    openai_max_retries = _parse_int(
        env_values.get("GEOQA_OPENAI_MAX_RETRIES"),
        name="GEOQA_OPENAI_MAX_RETRIES",
        default=2,
        minimum=0,
    )
    openai_retry_backoff_seconds = _parse_float(
        env_values.get("GEOQA_OPENAI_RETRY_BACKOFF_SECONDS"),
        name="GEOQA_OPENAI_RETRY_BACKOFF_SECONDS",
        default=1.0,
        minimum=0.0,
    )
    agent_max_steps = _parse_int(
        env_values.get("GEOQA_AGENT_MAX_STEPS"),
        name="GEOQA_AGENT_MAX_STEPS",
        default=6,
        minimum=1,
    )
    agent_output_token_budget = _parse_int(
        env_values.get("GEOQA_AGENT_OUTPUT_TOKEN_BUDGET"),
        name="GEOQA_AGENT_OUTPUT_TOKEN_BUDGET",
        default=1600,
        minimum=100,
    )
    return AppConfig(
        openai_api_key=env_values.get("OPENAI_API_KEY"),
        llm_model=env_values.get("GEOQA_LLM_MODEL"),
        output_root=output_root,
        agent_report_enabled=agent_report_enabled,
        openai_timeout_seconds=openai_timeout_seconds,
        openai_max_retries=openai_max_retries,
        openai_retry_backoff_seconds=openai_retry_backoff_seconds,
        agent_max_steps=agent_max_steps,
        agent_output_token_budget=agent_output_token_budget,
        env_file=str(resolved_env) if resolved_env else None,
    )


def diagnose_config(config: AppConfig) -> dict[str, Any]:
    issues: list[str] = []
    if not config.agent_report_enabled:
        issues.append("Agent reports are disabled by configuration.")
    if not config.llm_model:
        issues.append("GEOQA_LLM_MODEL is not configured.")
    if not config.openai_api_key:
        issues.append("OPENAI_API_KEY is not configured.")
    return {
        "config": config.to_safe_dict(),
        "checks": {
            "agent_report_enabled": config.agent_report_enabled,
            "openai_api_key_configured": bool(config.openai_api_key),
            "llm_model_configured": bool(config.llm_model),
            "output_root": config.output_root,
            "agent_max_steps": config.agent_max_steps,
            "agent_output_token_budget": config.agent_output_token_budget,
        },
        "issues": issues,
    }


def _load_env_file(env_file: str | None) -> tuple[Path | None, dict[str, str]]:
    candidate = Path(env_file) if env_file else Path(".env")
    if not candidate.exists():
        return None, {}
    values: dict[str, str] = {}
    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        values[key] = value
    return candidate, values


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigError(f"Invalid boolean value: {raw}")


def _parse_float(raw: str | None, *, name: str, default: float, minimum: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}.")
    return value


def _parse_int(raw: str | None, *, name: str, default: int, minimum: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}.")
    return value
