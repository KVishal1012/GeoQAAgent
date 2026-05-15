from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReviewError(RuntimeError):
    """Raised when an agent report cannot be reviewed or finalized."""


@dataclass(slots=True)
class ReviewStatus:
    status: str
    reviewer_name: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None
    draft_path: str | None = None
    final_path: str | None = None
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_review_status(output_dir: str | Path, status: ReviewStatus) -> str:
    path = Path(output_dir) / "review_status.json"
    path.write_text(json.dumps(status.to_dict(), indent=2), encoding="utf-8")
    return str(path)


def approve_agent_report(output_dir: str | Path, reviewer_name: str, notes: str | None = None) -> ReviewStatus:
    if not reviewer_name:
        raise ReviewError("reviewer_name is required to approve an agent report.")

    output_path = Path(output_dir)
    draft_path = output_path / "agent_report_draft.md"
    consistency_path = output_path / "report_consistency.json"
    hallucination_path = output_path / "hallucination_check.json"
    final_path = output_path / "agent_report.md"

    if not draft_path.exists():
        raise ReviewError("agent_report_draft.md does not exist.")
    for check_path in (consistency_path, hallucination_path):
        if not check_path.exists():
            raise ReviewError(f"{check_path.name} does not exist.")
        payload = json.loads(check_path.read_text(encoding="utf-8"))
        if not payload.get("passed"):
            raise ReviewError(f"{check_path.name} did not pass.")

    shutil.copyfile(draft_path, final_path)
    status = ReviewStatus(
        status="approved",
        reviewer_name=reviewer_name,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
        draft_path=str(draft_path),
        final_path=str(final_path),
    )
    write_review_status(output_path, status)
    return status

