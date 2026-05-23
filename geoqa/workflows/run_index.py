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
    latest_by_run_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", ""))
        if not run_id:
            continue
        latest_by_run_id[run_id] = _refresh_review_status(dict(row))
    return sorted(
        latest_by_run_id.values(),
        key=lambda row: row.get("finished_at") or row.get("started_at") or "",
        reverse=True,
    )


def sync_run_index_entry(output_dir: str | Path) -> str | None:
    output_path = Path(output_dir)
    output_root = output_path.parent
    index_path = output_root / "run_index.jsonl"
    if not index_path.exists():
        return None

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    target_output_dir = str(output_path)
    refreshed_rows: list[dict[str, Any]] = []
    updated = False
    for row in rows:
        refreshed = dict(row)
        if refreshed.get("output_dir") == target_output_dir:
            refreshed = _refresh_review_status(refreshed)
            updated = True
        refreshed_rows.append(refreshed)

    if not updated:
        return None

    index_path.write_text("\n".join(json.dumps(row) for row in refreshed_rows) + "\n", encoding="utf-8")
    return str(index_path)


def build_run_index_entry(qa_result: QAResult) -> dict[str, Any]:
    output_dir = Path(qa_result.artifact_paths.get("output_dir", ""))
    review_status = _read_json_if_exists(output_dir / "review_status.json")
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


def _refresh_review_status(row: dict[str, Any]) -> dict[str, Any]:
    output_dir = row.get("output_dir")
    if not output_dir:
        return row
    review_status = _read_json_if_exists(Path(output_dir) / "review_status.json")
    row["review_status"] = review_status.get("status") if review_status else None
    return row


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
