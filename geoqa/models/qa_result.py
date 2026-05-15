from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .issue import Issue
from .run_record import RunRecord


@dataclass(slots=True)
class QAResult:
    """Aggregate result returned by the runner."""

    run_record: RunRecord
    issues: list[Issue] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)

    @property
    def issue_counts(self) -> dict[str, int]:
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in self.issues:
            if issue.severity in counts:
                counts[issue.severity] += 1
        counts["total"] = len(self.issues)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_record": self.run_record.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": dict(self.summary),
            "artifact_paths": dict(self.artifact_paths),
            "issue_counts": self.issue_counts,
        }
