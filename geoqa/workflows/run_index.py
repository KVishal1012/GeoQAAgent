from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geoqa.models import QAResult


def append_run_index(qa_result: QAResult, output_root: str | Path) -> str:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    entry = build_run_index_entry(qa_result)
    path = output_root_path / "run_index.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return str(path)


def load_run_index(output_root: str | Path) -> list[dict[str, Any]]:
    path = Path(output_root) / "run_index.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(rows, key=lambda row: row.get("finished_at") or row.get("started_at") or "", reverse=True)


def build_run_index_entry(qa_result: QAResult) -> dict[str, Any]:
    review_status = _read_json_if_exists(Path(qa_result.artifact_paths.get("output_dir", "")) / "review_status.json")
    return {
        "run_id": qa_result.run_record.run_id,
        "dataset_name": qa_result.run_record.filename,
        "started_at": qa_result.run_record.started_at,
        "finished_at": qa_result.run_record.finished_at,
        "readiness_band": qa_result.run_record.readiness_band,
        "readiness_score": qa_result.run_record.readiness_score,
        "issue_counts": dict(qa_result.run_record.issue_counts),
        "output_dir": qa_result.artifact_paths.get("output_dir"),
        "artifact_paths": dict(qa_result.artifact_paths),
        "review_status": review_status.get("status") if review_status else None,
    }


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
