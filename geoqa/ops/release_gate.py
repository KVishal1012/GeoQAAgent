from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

EXPECTED_RUNTIME_CONTRACT = "v1.2"
REQUIRED_PACKAGE_ARTIFACTS = ("final_customer_report_pdf", "issues_csv", "handoff_bundle")


@dataclass(slots=True)
class ReleaseGateResult:
    passed: bool
    checks: dict[str, bool]
    blocking_errors: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fetch_json(base_url: str, path: str, api_key: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{path} could not be reached: {exc.reason}") from exc


def run_release_gate(
    base_url: str,
    *,
    api_key: str | None = None,
    run_id: str | None = None,
    require_approved_package: bool = False,
) -> ReleaseGateResult:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    evidence: dict[str, Any] = {}

    try:
        health = _fetch_json(base_url, "/health")
        evidence["api_health"] = health
        checks["api_healthy"] = health.get("status") == "healthy"
        checks["api_contract_compatible"] = health.get("runtime_contract_version") == EXPECTED_RUNTIME_CONTRACT
    except RuntimeError as exc:
        checks["api_healthy"] = False
        checks["api_contract_compatible"] = False
        errors.append(str(exc))

    try:
        config = _fetch_json(base_url, "/config")
        evidence["config"] = {
            "supabase_configured": config.get("supabase_configured"),
            "runtime_contract_version": config.get("runtime_contract_version"),
            "active_max_upload_mb": config.get("active_max_upload_mb"),
        }
        checks["supabase_configured"] = bool(config.get("supabase_configured"))
        checks["config_contract_compatible"] = config.get("runtime_contract_version") == EXPECTED_RUNTIME_CONTRACT
    except RuntimeError as exc:
        checks["supabase_configured"] = False
        checks["config_contract_compatible"] = False
        errors.append(str(exc))

    try:
        operations = _fetch_json(base_url, "/api/v1/operations/health", api_key)
        evidence["operations"] = operations
        worker = operations.get("worker") or {}
        queue = operations.get("queue") or {}
        queued_work = sum(
            int(queue.get(key) or 0)
            for key in ("qa_queued", "qa_running", "packages_queued", "packages_building")
        )
        checks["worker_available_for_queue"] = worker.get("status") == "online" or queued_work == 0
        checks["worker_contract_compatible"] = bool(operations.get("compatible"))
    except RuntimeError as exc:
        checks["worker_available_for_queue"] = False
        checks["worker_contract_compatible"] = False
        errors.append(str(exc))

    if run_id:
        try:
            run = _fetch_json(base_url, f"/api/v1/runs/{run_id}", api_key)
            evidence["run"] = {
                "run_id": run_id,
                "status": run.get("status"),
                "review_status": (run.get("review_status") or {}).get("status"),
                "package_status": run.get("package_status"),
            }
            checks["run_completed"] = run.get("status") == "completed"
            if require_approved_package:
                checks["run_approved"] = (run.get("review_status") or {}).get("status") == "approved"
                checks["package_ready"] = run.get("package_status") == "ready"
                artifacts = run.get("artifacts") or {}
                missing = [name for name in REQUIRED_PACKAGE_ARTIFACTS if not (artifacts.get(name) or {}).get("exists")]
                checks["customer_artifacts_ready"] = not missing
                if missing:
                    errors.append(f"Run {run_id} is missing required customer artifacts: {', '.join(missing)}.")
        except RuntimeError as exc:
            checks["run_completed"] = False
            errors.append(str(exc))

    for name, passed in checks.items():
        if not passed and not any(name.replace("_", " ") in error.lower() for error in errors):
            errors.append(f"Release check failed: {name.replace('_', ' ')}.")
    return ReleaseGateResult(passed=all(checks.values()) if checks else False, checks=checks, blocking_errors=errors, evidence=evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate GeoQA V1.2 API, storage, worker, and package compatibility.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", default=os.getenv("GEOQA_API_KEY"))
    parser.add_argument("--run-id")
    parser.add_argument("--require-approved-package", action="store_true")
    args = parser.parse_args()
    result = run_release_gate(
        args.base_url,
        api_key=args.api_key,
        run_id=args.run_id,
        require_approved_package=args.require_approved_package,
    )
    print(json.dumps(result.to_dict(), indent=2))
    raise SystemExit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
