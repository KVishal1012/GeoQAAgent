from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from geoqa.ops.pipeline_gate import evaluate_pipeline_gate, validate_fail_below_threshold
from geoqa.runner import run_geoqa

SUPPORTED_DROP_EXTENSIONS = {".geojson", ".gpkg", ".zip"}


def scan_watch_folder_once(
    watch_dir: str | Path,
    *,
    output_root: str | Path,
    state_file: str | Path | None = None,
    fail_below: int | None = None,
    required_columns: list[str] | None = None,
    target_crs: str | None = None,
    precision_grid_size: float | None = None,
    enable_sqlserver_checks: bool = True,
    enable_linear_reference_checks: bool = True,
    slack_webhook_url: str | None = None,
    min_age_seconds: float = 0.0,
) -> dict[str, Any]:
    """Process new geospatial drops in a folder once and persist a lightweight state file."""

    validate_fail_below_threshold(fail_below)
    watch_path = Path(watch_dir).expanduser().resolve()
    if not watch_path.exists() or not watch_path.is_dir():
        raise ValueError(f"watch_dir does not exist or is not a directory: {watch_path}")
    output_path = Path(output_root).expanduser()
    state_path = Path(state_file).expanduser() if state_file else output_path / "watch_state.json"
    state = _load_state(state_path)
    now = time.time()
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in _discover_drops(watch_path):
        signature = _file_signature(candidate)
        state_key = str(candidate)
        if state.get("files", {}).get(state_key) == signature:
            skipped.append({"path": str(candidate), "reason": "already_processed"})
            continue
        age_seconds = now - candidate.stat().st_mtime
        if age_seconds < min_age_seconds:
            skipped.append({"path": str(candidate), "reason": "too_new"})
            continue

        record: dict[str, Any] = {"path": str(candidate), "status": "running"}
        try:
            result = run_geoqa(
                input_path=str(candidate),
                output_root=str(output_path),
                required_columns=required_columns,
                target_crs=target_crs,
                precision_grid_size=precision_grid_size,
                enable_sqlserver_checks=enable_sqlserver_checks,
                enable_linear_reference_checks=enable_linear_reference_checks,
            )
            gate = evaluate_pipeline_gate(result.run_record.readiness_score, fail_below)
            record.update(
                {
                    "status": "completed",
                    "run_id": result.run_record.run_id,
                    "readiness_score": result.run_record.readiness_score,
                    "readiness_band": result.run_record.readiness_band,
                    "issue_counts": result.run_record.issue_counts,
                    "output_dir": result.artifact_paths.get("output_dir"),
                    "pipeline_gate": gate.to_dict() if gate else None,
                }
            )
            if gate and not gate.passed and slack_webhook_url:
                alert_payload = build_slack_alert_payload(record, gate.to_dict())
                send_slack_alert(slack_webhook_url, alert_payload)
                record["alert_sent"] = True
            state.setdefault("files", {})[state_key] = signature
        except Exception as exc:  # pragma: no cover - exercised through CLI failure paths
            record.update({"status": "failed", "error": str(exc)})
        processed.append(record)

    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_state(state_path, state)
    return {
        "watch_dir": str(watch_path),
        "output_root": str(output_path),
        "state_file": str(state_path),
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "processed": processed,
        "skipped": skipped,
    }


def watch_folder(
    watch_dir: str | Path,
    *,
    output_root: str | Path,
    interval_seconds: float = 60.0,
    once: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Watch a folder continuously, or run one scan when once=True."""

    if once:
        return scan_watch_folder_once(watch_dir, output_root=output_root, **kwargs)
    latest: dict[str, Any] = {}
    while True:
        latest = scan_watch_folder_once(watch_dir, output_root=output_root, **kwargs)
        time.sleep(interval_seconds)
    return latest


def build_slack_alert_payload(run_record: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    dataset = Path(str(run_record.get("path", "dataset"))).name
    score = gate.get("readiness_score")
    threshold = gate.get("threshold")
    band = run_record.get("readiness_band") or "unknown"
    output_dir = run_record.get("output_dir") or "not available"
    return {
        "text": f"GeoQA gate blocked {dataset}: score {score}/100 below threshold {threshold}/100.",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*GeoQA pipeline gate blocked a dataset*\n"
                        f"*Dataset:* `{dataset}`\n"
                        f"*Score:* `{score}/100`\n"
                        f"*Threshold:* `{threshold}/100`\n"
                        f"*Band:* `{band}`"
                    ),
                },
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": f"Artifacts: `{output_dir}`"}},
        ],
    }


def send_slack_alert(webhook_url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def _discover_drops(watch_dir: Path) -> list[Path]:
    return sorted(
        path for path in watch_dir.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in SUPPORTED_DROP_EXTENSIONS
    )


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size_bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
