import json
from pathlib import Path

import pytest

from geoqa.config import ConfigError, diagnose_config, load_app_config


def test_load_app_config_reads_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "GEOQA_LLM_MODEL=gpt-test",
                "GEOQA_OUTPUT_ROOT=/tmp/geoqa-outputs",
                "GEOQA_AGENT_REPORT_ENABLED=true",
                "GEOQA_OPENAI_TIMEOUT_SECONDS=45",
                "GEOQA_OPENAI_MAX_RETRIES=3",
                "GEOQA_OPENAI_RETRY_BACKOFF_SECONDS=2.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOQA_LLM_MODEL", raising=False)

    config = load_app_config(str(env_file))

    assert config.openai_api_key == "test-key"
    assert config.llm_model == "gpt-test"
    assert config.output_root == "/tmp/geoqa-outputs"
    assert config.openai_timeout_seconds == 45.0
    assert config.openai_max_retries == 3
    assert config.openai_retry_backoff_seconds == 2.5


def test_load_app_config_uses_defaults_for_static_internal_mode(monkeypatch):
    for key in (
        "OPENAI_API_KEY",
        "GEOQA_LLM_MODEL",
        "GEOQA_OUTPUT_ROOT",
        "GEOQA_AGENT_REPORT_ENABLED",
        "GEOQA_OPENAI_TIMEOUT_SECONDS",
        "GEOQA_OPENAI_MAX_RETRIES",
        "GEOQA_OPENAI_RETRY_BACKOFF_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    config = load_app_config()

    assert config.output_root == "outputs"
    assert config.agent_report_enabled is True
    assert config.openai_timeout_seconds == 30.0
    assert config.openai_max_retries == 2
    assert config.openai_retry_backoff_seconds == 1.0


def test_load_app_config_rejects_invalid_timeout(monkeypatch):
    monkeypatch.setenv("GEOQA_OPENAI_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigError, match="GEOQA_OPENAI_TIMEOUT_SECONDS"):
        load_app_config()


def test_diagnose_config_reports_missing_openai_settings(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEOQA_LLM_MODEL", raising=False)

    diagnosis = diagnose_config(load_app_config())

    assert diagnosis["checks"]["openai_api_key_configured"] is False
    assert diagnosis["checks"]["llm_model_configured"] is False
    assert any("OPENAI_API_KEY" in issue for issue in diagnosis["issues"])



def test_load_app_config_reads_production_mvp_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    monkeypatch.setenv("GEOQA_UPLOAD_BUCKET", "uploads")
    monkeypatch.setenv("GEOQA_ARTIFACT_BUCKET", "artifacts")
    monkeypatch.setenv("GEOQA_MAX_UPLOAD_MB", "25")
    monkeypatch.setenv("GEOQA_WORKER_POLL_SECONDS", "2.5")
    monkeypatch.setenv("GEOQA_LARGE_FILE_MODE", "true")
    monkeypatch.setenv("GEOQA_LARGE_FILE_MAX_UPLOAD_MB", "1024")
    monkeypatch.setenv("GEOQA_WORKER_ID", "worker-a")
    monkeypatch.setenv("GEOQA_WORKER_STALE_AFTER_SECONDS", "60")
    monkeypatch.setenv("GEOQA_WORKER_MAX_ATTEMPTS", "5")

    config = load_app_config()

    assert config.supabase_url == "https://example.supabase.co"
    assert config.supabase_service_role_key == "service-role"
    assert config.supabase_public_key == "publishable"
    assert config.upload_bucket == "uploads"
    assert config.artifact_bucket == "artifacts"
    assert config.max_upload_mb == 25
    assert config.large_file_mode is True
    assert config.large_file_max_upload_mb == 1024
    assert config.worker_poll_seconds == 2.5
    assert config.worker_id == "worker-a"
    assert config.worker_stale_after_seconds == 60
    assert config.worker_max_attempts == 5
    assert config.to_safe_dict()["supabase_service_role_key"] == "***configured***"
    assert config.to_safe_dict()["supabase_public_key"] == "***configured***"


def test_load_app_config_uses_tmp_output_root_on_vercel(monkeypatch):
    monkeypatch.delenv("GEOQA_OUTPUT_ROOT", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    config = load_app_config()

    assert config.output_root == "/tmp/geoqa-outputs"
