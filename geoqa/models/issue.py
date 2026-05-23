from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Issue:
    """A normalized QA finding for a dataset or feature."""

    issue_code: str
    check_name: str
    message: str
    severity: str | None = None
    feature_id: str | int | None = None
    suggested_fix: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.context:
            payload["context"] = {}
        return payload
