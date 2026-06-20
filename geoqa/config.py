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
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_public_key: str | None
    upload_bucket: str
    artifact_bucket: str
    max_upload_mb: int
    large_file_mode: bool
    large_file_max_upload_mb: int
    worker_poll_seconds: float
    worker_id: str
    worker_stale_after_seconds: int
    worker_max_attempts: int
    env_file: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["openai_api_key"] = "***configured***" if self.openai_api_key else None
        payload["supabase_service_role_key"] = "***configured***" if self.supabase_service_role_key else None
        payload["supabase_public_key"] = "***configured***" if self.supabase_public_key else None
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

    output_root = _default_output_root(env_values)
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
    max_upload_mb = _parse_int(
        env_values.get("GEOQA_MAX_UPLOAD_MB"),
        name="GEOQA_MAX_UPLOAD_MB",
        default=100,
        minimum=1,
    )
    large_file_mode = _parse_bool(env_values.get("GEOQA_LARGE_FILE_MODE"), default=False)
    large_file_max_upload_mb = _parse_int(
        env_values.get("GEOQA_LARGE_FILE_MAX_UPLOAD_MB"),
        name="GEOQA_LARGE_FILE_MAX_UPLOAD_MB",
        default=1024,
        minimum=1,
    )
    worker_poll_seconds = _parse_float(
        env_values.get("GEOQA_WORKER_POLL_SECONDS"),
        name="GEOQA_WORKER_POLL_SECONDS",
        default=5.0,
        minimum=0.1,
    )
    worker_stale_after_seconds = _parse_int(
        env_values.get("GEOQA_WORKER_STALE_AFTER_SECONDS"),
        name="GEOQA_WORKER_STALE_AFTER_SECONDS",
        default=900,
        minimum=1,
    )
    worker_max_attempts = _parse_int(
        env_values.get("GEOQA_WORKER_MAX_ATTEMPTS"),
        name="GEOQA_WORKER_MAX_ATTEMPTS",
        default=3,
        minimum=1,
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
        supabase_url=env_values.get("SUPABASE_URL"),
        supabase_service_role_key=env_values.get("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_public_key=env_values.get("SUPABASE_PUBLISHABLE_KEY") or env_values.get("SUPABASE_ANON_KEY"),
        upload_bucket=env_values.get("GEOQA_UPLOAD_BUCKET", "geoqa-uploads").strip() or "geoqa-uploads",
        artifact_bucket=env_values.get("GEOQA_ARTIFACT_BUCKET", "geoqa-artifacts").strip() or "geoqa-artifacts",
        max_upload_mb=max_upload_mb,
        large_file_mode=large_file_mode,
        large_file_max_upload_mb=large_file_max_upload_mb,
        worker_poll_seconds=worker_poll_seconds,
        worker_id=env_values.get("GEOQA_WORKER_ID", "geoqa-worker").strip() or "geoqa-worker",
        worker_stale_after_seconds=worker_stale_after_seconds,
        worker_max_attempts=worker_max_attempts,
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
            "supabase_configured": bool(config.supabase_url and config.supabase_service_role_key),
            "supabase_public_key_configured": bool(config.supabase_public_key),
            "upload_bucket": config.upload_bucket,
            "artifact_bucket": config.artifact_bucket,
            "max_upload_mb": config.max_upload_mb,
            "large_file_mode": config.large_file_mode,
            "large_file_max_upload_mb": config.large_file_max_upload_mb,
            "worker_poll_seconds": config.worker_poll_seconds,
            "worker_id": config.worker_id,
            "worker_stale_after_seconds": config.worker_stale_after_seconds,
            "worker_max_attempts": config.worker_max_attempts,
        },
        "issues": issues,
    }


def _default_output_root(env_values: dict[str, str]) -> str:
    configured = env_values.get("GEOQA_OUTPUT_ROOT")
    if configured and configured.strip():
        return configured.strip()
    if env_values.get("VERCEL"):
        return "/tmp/geoqa-outputs"
    return "outputs"


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
