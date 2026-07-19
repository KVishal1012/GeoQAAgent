from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from geoqa.config import load_app_config
from geoqa.production.store import BaseProductionStore, ProductionStoreError, build_production_store
from geoqa.runner import run_geoqa


def process_next_run(store: BaseProductionStore | None = None, *, output_root: str | Path | None = None) -> dict[str, Any] | None:
    config = load_app_config()
    store = store or build_production_store(config)
    run = store.claim_next_run(
        worker_id=config.worker_id,
        stale_after_seconds=config.worker_stale_after_seconds,
        max_attempts=config.worker_max_attempts,
    )
    if not run:
        return None

    run_id = str(run["run_id"])
    try:
        store.heartbeat_run(run_id, worker_id=config.worker_id)
        with tempfile.TemporaryDirectory(prefix="geoqa-worker-") as temp_dir:
            input_path = store.download_upload(run, Path(temp_dir) / "input")
            store.heartbeat_run(run_id, worker_id=config.worker_id)
            qa_output_root = Path(output_root or config.output_root) / "worker_runs"
            result = run_geoqa(
                str(input_path),
                output_root=str(qa_output_root),
                required_columns=list(run.get("required_columns") or []),
                target_crs=run.get("target_crs"),
                customer_intake=run.get("customer_intake") or {},
            )
            store.heartbeat_run(run_id, worker_id=config.worker_id)
            artifacts = store.upload_artifacts(run_id, result.artifact_paths["output_dir"])
            run_summary = {key: value for key, value in result.summary.items() if key != "map_preview"}
            completed = store.update_run(
                run_id,
                status="completed",
                run_output_dir=result.artifact_paths["output_dir"],
                readiness_score=result.run_record.readiness_score,
                readiness_band=result.run_record.readiness_band,
                issue_counts=result.issue_counts,
                run_summary=run_summary,
                run_record=result.run_record.to_dict(),
                artifacts=artifacts,
                error=None,
                error_type=None,
            )
            return completed
    except Exception as exc:
        safe_error = "GeoQA processing failed. Review the worker logs for details."
        try:
            current = store.get_run(run_id)
            attempts = int(current.get("attempt_count") or run.get("attempt_count") or 1)
            max_attempts = int(current.get("max_attempts") or config.worker_max_attempts)
            next_status = "failed" if attempts >= max_attempts else "queued"
            return store.update_run(
                run_id,
                status=next_status,
                error=safe_error,
                error_type=type(exc).__name__,
                last_heartbeat_at=None if next_status == "queued" else current.get("last_heartbeat_at"),
                claimed_by=None if next_status == "queued" else current.get("claimed_by"),
                claimed_at=None if next_status == "queued" else current.get("claimed_at"),
            )
        except ProductionStoreError:
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued GeoQA production MVP upload runs.")
    parser.add_argument("--once", action="store_true", help="Process one queued run and exit.")
    parser.add_argument("--poll-seconds", type=float, default=None, help="Polling interval for continuous worker mode.")
    args = parser.parse_args()

    config = load_app_config()
    poll_seconds = args.poll_seconds if args.poll_seconds is not None else config.worker_poll_seconds
    while True:
        result = process_next_run()
        if result is not None:
            print(json.dumps(result, indent=2), flush=True)
        if args.once:
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
