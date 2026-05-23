from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PromptRegistryError(KeyError):
    """Raised when a prompt template is unavailable."""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    path: Path
    text: str

    def render(self, values: dict[str, str]) -> str:
        rendered = self.text
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered


class PromptRegistry:
    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        self.prompt_dir = Path(prompt_dir) if prompt_dir else Path(__file__).parent / "prompts"

    def get(self, name: str) -> PromptTemplate:
        path = self.prompt_dir / f"{name}.md"
        if not path.exists():
            raise PromptRegistryError(f"Prompt template not found: {name}")
        return PromptTemplate(name=name, path=path, text=path.read_text(encoding="utf-8"))

    def render(self, name: str, values: dict[str, str]) -> str:
        return self.get(name).render(values)

