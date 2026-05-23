import sys
import types

import pytest

from geoqa.config import load_app_config
from geoqa.llm.gateway import LLMGatewayError, OpenAILLMGateway, build_openai_gateway


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class FakeResponse:
    id = "resp_test"
    output_text = "Grounded report text."


def _install_fake_openai(monkeypatch, side_effects):
    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            effect = side_effects[self.calls]
            self.calls += 1
            if isinstance(effect, Exception):
                raise effect
            return effect

    class FakeClient:
        def __init__(self, api_key=None, timeout=None):
            self.api_key = api_key
            self.timeout = timeout
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeClient))


def test_gateway_retries_transient_failure_and_succeeds(monkeypatch):
    _install_fake_openai(monkeypatch, [APIConnectionError("temporary"), FakeResponse()])
    monkeypatch.setattr("geoqa.llm.gateway.time.sleep", lambda *_args, **_kwargs: None)

    gateway = OpenAILLMGateway(
        api_key="test-key",
        default_model="gpt-test",
        timeout_seconds=12.0,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )
    response = gateway.generate("prompt")

    assert response.text == "Grounded report text."
    assert response.raw["timeout_seconds"] == 12.0


def test_gateway_raises_timeout_error_after_retries(monkeypatch):
    _install_fake_openai(monkeypatch, [APITimeoutError("slow"), APITimeoutError("still slow")])
    monkeypatch.setattr("geoqa.llm.gateway.time.sleep", lambda *_args, **_kwargs: None)

    gateway = OpenAILLMGateway(
        api_key="test-key",
        default_model="gpt-test",
        timeout_seconds=5.0,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )

    with pytest.raises(LLMGatewayError) as exc:
        gateway.generate("prompt")

    assert exc.value.code == "timeout"
    assert exc.value.transient is True


def test_gateway_respects_disabled_agent_mode(monkeypatch):
    monkeypatch.setenv("GEOQA_AGENT_REPORT_ENABLED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEOQA_LLM_MODEL", "gpt-test")
    config = load_app_config()

    with pytest.raises(LLMGatewayError) as exc:
        build_openai_gateway(config)

    assert exc.value.code == "agent_reports_disabled"
