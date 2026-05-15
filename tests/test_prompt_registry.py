from pathlib import Path

import pytest

from geoqa.llm.prompt_registry import PromptRegistry, PromptRegistryError


def test_prompt_registry_renders_prompt_values(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "sample_v1.md").write_text("Evidence: {{EVIDENCE_JSON}}", encoding="utf-8")

    rendered = PromptRegistry(prompt_dir).render("sample_v1", {"EVIDENCE_JSON": "{\"score\": 100}"})

    assert rendered == "Evidence: {\"score\": 100}"


def test_prompt_registry_raises_for_missing_prompt(tmp_path):
    with pytest.raises(PromptRegistryError):
        PromptRegistry(Path(tmp_path)).get("missing_v1")

