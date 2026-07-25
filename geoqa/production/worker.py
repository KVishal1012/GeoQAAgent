from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geoqa.config import load_app_config
from geoqa.llm.gateway import LLMGateway
from geoqa.production.report_workflow import generate_bounded_report_draft
from geoqa.production.store import BaseProductionStore, ProductionStoreError, build_production_store
from geoqa.runner import run_geoqa
from geoqa.workflows import export_handoff_bundle, generate_fix_plan_artifacts


PACKAGE_SOURCE_ARTIFACTS = [
    "qa_report",
    "issues_csv",
    "summary",
    "run_record",
    "geometry_profile",
    "map_preview",
    "customer_report",
    "customer_report_pdf",
    "customer_intake",
    "agent_report_draft",
    "agent_report",
    "agent_report_json",
    "agent_session",
    "agent_trace",
    "report_consistency",
    "hallucination_check",
    "review_status",
    "review_history",
    "final_customer_report",
    "final_customer_report_pdf",
    "fix_plan",
    "fix_plan_json",
]


@contextmanager
def _heartbeat_guard(callback, *, stale_after_seconds: int):
    stop_event = threading.Event()
    interval_seconds = max(1.0, min(30.0, stale_after_seconds / 3))

    def heartbeat_loop() -> None:
        while not stop_event.wait(interval_seconds):
            try:
                callback()
            except Exception:
                # The foreground operation remains authoritative and will record
                # a safe failure if storage connectivity does not recover.
                continue

    thread = threading.Thread(target=heartbeat_loop, name="geoqa-worker-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


def process_next_run(
    store: BaseProductionStore | None = None,
    *,
    output_root: str | Path | None = None,
    agent_gateway: LLMGateway | None = None,
) -> dict[str, Any] | None:
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
        with _heartbeat_guard(
            lambda: store.heartbeat_run(run_id, worker_id=config.worker_id),
            stale_after_seconds=config.worker_stale_after_seconds,
        ):
            with tempfile.TemporaryDirectory(prefix="geoqa-worker-") as temp_dir:
                input_path = store.download_upload(run, Path(temp_dir) / "input")
                qa_output_root = Path(output_root or config.output_root) / "worker_runs"
                result = run_geoqa(
                    str(input_path),
                    output_root=str(qa_output_root),
                    required_columns=list(run.get("required_columns") or []),
                    target_crs=run.get("target_crs"),
                    customer_intake=run.get("customer_intake") or {},
                )
                generate_fix_plan_artifacts(result.artifact_paths["output_dir"])
                review_status = generate_bounded_report_draft(result, config, gateway=agent_gateway)
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
                    review_status=review_status,
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


def process_next_package(
    store: BaseProductionStore | None = None,
) -> dict[str, Any] | None:
    config = load_app_config()
    store = store or build_production_store(config)
    run = store.claim_next_package(
        worker_id=config.worker_id,
        stale_after_seconds=config.worker_stale_after_seconds,
        max_attempts=config.worker_max_attempts,
    )
    if not run:
        return None

    run_id = str(run["run_id"])
    try:
        store.heartbeat_package(run_id, worker_id=config.worker_id)
        with _heartbeat_guard(
            lambda: store.heartbeat_package(run_id, worker_id=config.worker_id),
            stale_after_seconds=config.worker_stale_after_seconds,
        ):
            with tempfile.TemporaryDirectory(prefix="geoqa-package-") as temp_dir:
                output_dir = Path(temp_dir)
                available = run.get("artifacts") or {}
                for artifact_name in PACKAGE_SOURCE_ARTIFACTS:
                    artifact = available.get(artifact_name) or {}
                    if not artifact.get("exists"):
                        continue
                    data, filename, _ = store.artifact_bytes(run, artifact_name)
                    (output_dir / Path(filename).name).write_bytes(data)

                export_handoff_bundle(output_dir, include_comparison=False)
                changed_artifacts = store.upload_artifact_subset(
                    run_id,
                    output_dir,
                    ["bundle_manifest", "handoff_bundle"],
                )

        merged_artifacts = dict(available)
        merged_artifacts.update(changed_artifacts)
        completed = store.update_run(
            run_id,
            package_status="ready",
            package_completed_at=datetime.now(timezone.utc).isoformat(),
            package_claimed_at=None,
            package_claimed_by=None,
            package_last_heartbeat_at=None,
            package_error=None,
            package_error_type=None,
            artifacts=merged_artifacts,
        )
        store.append_event(run_id, "package_ready", {"artifacts": ["bundle_manifest", "handoff_bundle"]})
        return completed
    except Exception as exc:
        safe_error = "Customer package generation failed. Review the worker logs for details."
        try:
            current = store.get_run(run_id)
            attempts = int(current.get("package_attempt_count") or run.get("package_attempt_count") or 1)
            max_attempts = int(current.get("package_max_attempts") or config.worker_max_attempts)
            next_status = "failed" if attempts >= max_attempts else "queued"
            failed = store.update_run(
                run_id,
                package_status=next_status,
                package_error=safe_error,
                package_error_type=type(exc).__name__,
                package_last_heartbeat_at=None,
                package_claimed_by=None,
                package_claimed_at=None,
            )
            store.append_event(
                run_id,
                "package_failed" if next_status == "failed" else "package_requeued",
                {"attempt_count": attempts, "error_type": type(exc).__name__},
            )
            return failed
        except ProductionStoreError:
            raise


def process_next_work(
    store: BaseProductionStore | None = None,
    *,
    output_root: str | Path | None = None,
    agent_gateway: LLMGateway | None = None,
) -> dict[str, Any] | None:
    store = store or build_production_store(load_app_config())
    packaged = process_next_package(store=store)
    if packaged is not None:
        return packaged
    return process_next_run(store=store, output_root=output_root, agent_gateway=agent_gateway)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued GeoQA production MVP upload runs.")
    parser.add_argument("--once", action="store_true", help="Process one queued run and exit.")
    parser.add_argument("--poll-seconds", type=float, default=None, help="Polling interval for continuous worker mode.")
    args = parser.parse_args()

    config = load_app_config()
    poll_seconds = args.poll_seconds if args.poll_seconds is not None else config.worker_poll_seconds
    while True:
        result = process_next_work()
        if result is not None:
            print(json.dumps(result, indent=2), flush=True)
        if args.once:
            return
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
