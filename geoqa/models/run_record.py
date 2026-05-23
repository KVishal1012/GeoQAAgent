from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RunRecord:
    """Operational metadata for a single GeoQA run."""

    run_id: str
    input_path: str
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    duration_seconds: float | None = None
    status: str = "running"
    filename: str | None = None
    feature_count: int = 0
    geometry_types: list[str] = field(default_factory=list)
    crs: str | None = None
    enabled_checks: list[str] = field(default_factory=list)
    normalization_notes: list[str] = field(default_factory=list)
    readiness_score: int | None = None
    readiness_band: str | None = None
    issue_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
