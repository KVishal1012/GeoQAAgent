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
    queued = store.list_queued_runs(limit=1)
    if not queued:
        return None

    run = queued[0]
    run_id = str(run["run_id"])
    try:
        store.update_run(run_id, status="running", error=None)
        with tempfile.TemporaryDirectory(prefix="geoqa-worker-") as temp_dir:
            input_path = store.download_upload(run, Path(temp_dir) / "input")
            qa_output_root = Path(output_root or config.output_root) / "worker_runs"
            result = run_geoqa(
                str(input_path),
                output_root=str(qa_output_root),
                required_columns=list(run.get("required_columns") or []),
                target_crs=run.get("target_crs"),
            )
            artifacts = store.upload_artifacts(run_id, result.artifact_paths["output_dir"])
            completed = store.update_run(
                run_id,
                status="completed",
                run_output_dir=result.artifact_paths["output_dir"],
                readiness_score=result.run_record.readiness_score,
                readiness_band=result.run_record.readiness_band,
                issue_counts=result.issue_counts,
                artifacts=artifacts,
                error=None,
            )
            return completed
    except Exception as exc:
        safe_error = "GeoQA processing failed. Review the worker logs for details."
        try:
            return store.update_run(run_id, status="failed", error=safe_error, error_type=type(exc).__name__)
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
