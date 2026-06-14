from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievedPlaybook:
    source: str
    title: str
    text: str
    issue_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ISSUE_PLAYBOOK_MAP = {
    "MISSING_CRS": "crs_srid_playbook.md",
    "OUT_OF_RANGE_COORDINATES": "crs_srid_playbook.md",
    "SQLSERVER_MISSING_SRID": "crs_srid_playbook.md",
    "SQLSERVER_INCOMPATIBLE_COLUMN_NAME": "sql_server_spatial_errors.md",
    "DUPLICATE_GEOMETRY": "duplicate_geometry_playbook.md",
    "NULL_GEOMETRY": "geometry_fix_playbook.md",
    "EMPTY_GEOMETRY": "geometry_fix_playbook.md",
    "INVALID_GEOMETRY": "geometry_fix_playbook.md",
    "MIXED_GEOMETRY_TYPES": "geometry_fix_playbook.md",
    "OVERLAPPING_POLYGONS": "geometry_fix_playbook.md",
    "SUSPICIOUS_LARGE_FEATURE": "geometry_fix_playbook.md",
    "SUSPICIOUS_SMALL_FEATURE": "geometry_fix_playbook.md",
    "ZERO_LENGTH_LINE": "geometry_fix_playbook.md",
    "SPATIAL_OUTLIER": "spatial_anomaly_playbook.md",
    "MISSING_REQUIRED_COLUMN": "geometry_fix_playbook.md",
    "NON_STRING_COLUMN_NAME": "geometry_fix_playbook.md",
    "LONG_COLUMN_NAME": "geometry_fix_playbook.md",
    "NULL_HEAVY_COLUMN": "geometry_fix_playbook.md",
    "DUPLICATE_FEATURE_ID": "geometry_fix_playbook.md",
    "MISSING_LINEAR_MEASURE": "linear_referencing_rules.md",
    "REVERSED_LINEAR_MEASURE": "linear_referencing_rules.md",
}


def retrieve_playbooks(
    issues: list[dict[str, Any]],
    playbook_dir: str | Path | None = None,
) -> list[RetrievedPlaybook]:
    base_dir = Path(playbook_dir) if playbook_dir else Path(__file__).parent / "knowledge_base"
    file_to_codes: dict[str, set[str]] = {}
    for issue in issues:
        issue_code = str(issue.get("issue_code", ""))
        filename = ISSUE_PLAYBOOK_MAP.get(issue_code)
        if filename:
            file_to_codes.setdefault(filename, set()).add(issue_code)

    retrieved: list[RetrievedPlaybook] = []
    for filename, issue_codes in sorted(file_to_codes.items()):
        path = base_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        title = _extract_title(text, filename)
        retrieved.append(
            RetrievedPlaybook(
                source=str(path),
                title=title,
                text=text,
                issue_codes=sorted(issue_codes),
            )
        )
    return retrieved


def render_playbooks(playbooks: list[RetrievedPlaybook]) -> str:
    if not playbooks:
        return "No fix playbooks were retrieved for the detected issue codes."
    return "\n\n".join(playbook.text for playbook in playbooks)


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback

