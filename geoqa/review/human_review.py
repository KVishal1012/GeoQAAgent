from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReviewError(RuntimeError):
    """Raised when an agent report cannot be reviewed or finalized."""


VALID_REVIEW_STATES = {"draft_ready", "blocked", "rejected", "approved"}


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


def read_review_status(output_dir: str | Path) -> ReviewStatus | None:
    path = Path(output_dir) / "review_status.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReviewStatus(**payload)


def write_review_status(output_dir: str | Path, status: ReviewStatus) -> str:
    if status.status not in VALID_REVIEW_STATES:
        raise ReviewError(f"Invalid review status: {status.status}")
    path = Path(output_dir) / "review_status.json"
    path.write_text(json.dumps(status.to_dict(), indent=2), encoding="utf-8")
    return str(path)


def approve_agent_report(output_dir: str | Path, reviewer_name: str, notes: str | None = None) -> ReviewStatus:
    if not reviewer_name:
        raise ReviewError("reviewer_name is required to approve an agent report.")

    output_path = Path(output_dir)
    draft_path = output_path / "agent_report_draft.md"
    final_path = output_path / "agent_report.md"

    _validate_draft_and_checks(output_path, draft_path)

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


def reject_agent_report(output_dir: str | Path, reviewer_name: str, notes: str | None = None) -> ReviewStatus:
    if not reviewer_name:
        raise ReviewError("reviewer_name is required to reject an agent report.")

    output_path = Path(output_dir)
    draft_path = output_path / "agent_report_draft.md"
    final_path = output_path / "agent_report.md"

    if not draft_path.exists():
        raise ReviewError("agent_report_draft.md does not exist.")
    if final_path.exists():
        final_path.unlink()

    status = ReviewStatus(
        status="rejected",
        reviewer_name=reviewer_name,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
        draft_path=str(draft_path),
        final_path=None,
    )
    write_review_status(output_path, status)
    return status


def review_agent_report(
    output_dir: str | Path,
    action: str,
    reviewer_name: str,
    notes: str | None = None,
) -> ReviewStatus:
    if action == "approve":
        return approve_agent_report(output_dir, reviewer_name=reviewer_name, notes=notes)
    if action == "reject":
        return reject_agent_report(output_dir, reviewer_name=reviewer_name, notes=notes)
    raise ReviewError(f"Unsupported review action: {action}")


def _validate_draft_and_checks(output_path: Path, draft_path: Path) -> None:
    consistency_path = output_path / "report_consistency.json"
    hallucination_path = output_path / "hallucination_check.json"

    if not draft_path.exists():
        raise ReviewError("agent_report_draft.md does not exist.")
    for check_path in (consistency_path, hallucination_path):
        if not check_path.exists():
            raise ReviewError(f"{check_path.name} does not exist.")
        payload = json.loads(check_path.read_text(encoding="utf-8"))
        if not payload.get("passed"):
            raise ReviewError(f"{check_path.name} did not pass.")
