import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from api.index import _operations_health, _review_stored_report, app
from geoqa.config import load_app_config
from geoqa.ops.pilot import run_three_dataset_pilot
from geoqa.ops.release_gate import run_release_gate
from geoqa.production.store import ARTIFACT_NAMES, LocalProductionStore
from geoqa.runner import run_geoqa


def _write_geojson(path: Path, feature_id: str = "asset-1") -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"asset_id": feature_id},
                        "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class RemoteArtifactStore:
    def __init__(self, artifacts: dict[str, bytes]):
        self.contents = dict(artifacts)
        self.updates = {}
        self.events = []

    def artifact_bytes(self, run, artifact_name):
        filename = ARTIFACT_NAMES[artifact_name]
        return self.contents[artifact_name], filename, "application/octet-stream"

    def upload_artifact_subset(self, run_id, output_dir, artifact_names):
        output_path = Path(output_dir)
        uploaded = {}
        for name in artifact_names:
            filename = ARTIFACT_NAMES[name]
            path = output_path / filename
            exists = path.exists()
            if exists:
                self.contents[name] = path.read_bytes()
            uploaded[name] = {
                "filename": filename,
                "exists": exists,
                "storage_provider": "supabase",
                "storage_path": f"{run_id}/{filename}",
            }
        return uploaded

    def update_run(self, run_id, **updates):
        self.updates.update(updates)
        return {"run_id": run_id, **updates}

    def append_event(self, run_id, event_type, details=None):
        self.events.append((run_id, event_type, details or {}))


def test_remote_stored_approval_does_not_use_stale_worker_path():
    source = {
        "agent_report_draft": b"# Evidence-backed report\n\nThe dataset contains 1 feature.\n",
        "report_consistency": json.dumps({"passed": True}).encode(),
        "hallucination_check": json.dumps({"passed": True}).encode(),
        "review_status": json.dumps(
            {
                "status": "draft_ready",
                "draft_path": "/tmp/worker-that-no-longer-exists/agent_report_draft.md",
                "blocking_errors": [],
                "warnings": [],
            }
        ).encode(),
        "review_history": b"",
    }
    store = RemoteArtifactStore(source)
    run = {
        "run_id": "run-remote",
        "status": "completed",
        "run_output_dir": "/tmp/worker-that-no-longer-exists",
        "artifacts": {
            name: {"exists": True, "filename": ARTIFACT_NAMES[name], "storage_path": f"run-remote/{ARTIFACT_NAMES[name]}"}
            for name in source
        },
    }

    status, artifacts, package_status = _review_stored_report(
        store,
        run,
        action="approve",
        reviewer_name="QA Reviewer",
        notes="Remote evidence checked.",
    )

    assert status["status"] == "approved"
    assert artifacts["agent_report"]["exists"] is True
    assert artifacts["final_customer_report_pdf"]["exists"] is True
    assert store.contents["final_customer_report_pdf"][:4] == b"%PDF"
    assert package_status == "queued"
    assert store.updates["package_status"] == "queued"
    assert [event[1] for event in store.events] == ["review_approve", "package_queued"]


def test_operations_health_reports_queue_and_fresh_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_WORKER_STALE_AFTER_SECONDS", "60")
    store = LocalProductionStore(load_app_config())
    upload = tmp_path / "input.geojson"
    _write_geojson(upload)
    run = store.create_run(upload_id="upload-1", filename=upload.name, upload_storage_path=str(upload))
    store.update_run(
        run["run_id"],
        status="running",
        claimed_by="worker-v1-2",
        last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
        runtime_contract_version="v1.2",
    )

    payload = _operations_health(store)

    assert payload["status"] == "healthy"
    assert payload["worker"]["status"] == "online"
    assert payload["worker"]["worker_id"] == "worker-v1-2"
    assert payload["queue"]["qa_running"] == 1
    assert payload["compatible"] is True


def test_failed_run_and_package_can_be_manually_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    store = LocalProductionStore(load_app_config())
    upload = tmp_path / "input.geojson"
    _write_geojson(upload)
    run = store.create_run(upload_id="upload-1", filename=upload.name, upload_storage_path=str(upload))
    store.update_run(run["run_id"], status="failed", attempt_count=3, error="Safe failure")
    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    response = client.post(f"/api/v1/runs/{run['run_id']}/retry", headers=headers, json={"target": "run"})

    assert response.status_code == 202
    retried = store.get_run(run["run_id"])
    assert retried["status"] == "queued"
    assert retried["attempt_count"] == 0
    assert retried["error"] is None

    store.update_run(
        run["run_id"],
        status="completed",
        review_status={"status": "approved"},
        package_status="failed",
        package_attempt_count=3,
        package_error="Safe package failure",
    )
    response = client.post(f"/api/v1/runs/{run['run_id']}/retry", headers=headers, json={"target": "package"})

    assert response.status_code == 202
    retried = store.get_run(run["run_id"])
    assert retried["package_status"] == "queued"
    assert retried["package_attempt_count"] == 0
    assert retried["package_error"] is None


def test_customer_issue_csv_starts_with_plain_english_columns(tmp_path):
    input_path = tmp_path / "problem.geojson"
    input_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"asset_id": None}, "geometry": None}],
            }
        ),
        encoding="utf-8",
    )
    result = run_geoqa(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
        customer_intake={"intended_use": "sql_load"},
    )

    with Path(result.artifact_paths["issues_csv"]).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)

    assert reader.fieldnames[:5] == [
        "Severity",
        "Finding",
        "Affected record/column",
        "Why it matters",
        "Suggested action",
    ]
    assert row["Finding"]
    assert "SQL/database loading" in row["Why it matters"]
    assert row["issue_code"]


def test_release_gate_requires_compatible_worker_and_customer_package(monkeypatch):
    responses = {
        "/health": {"status": "healthy", "runtime_contract_version": "v1.2"},
        "/config": {"supabase_configured": True, "runtime_contract_version": "v1.2", "active_max_upload_mb": 100},
        "/api/v1/operations/health": {
            "status": "healthy",
            "compatible": True,
            "worker": {"status": "online"},
            "queue": {},
        },
        "/api/v1/runs/run-1": {
            "status": "completed",
            "review_status": {"status": "approved"},
            "package_status": "ready",
            "artifacts": {name: {"exists": True} for name in ("final_customer_report_pdf", "issues_csv", "handoff_bundle")},
        },
    }
    monkeypatch.setattr("geoqa.ops.release_gate._fetch_json", lambda base_url, path, api_key=None: responses[path])

    result = run_release_gate(
        "https://geoqa.example",
        api_key="secret",
        run_id="run-1",
        require_approved_package=True,
    )

    assert result.passed is True
    assert all(result.checks.values())


def test_three_dataset_pilot_writes_acceptance_results(tmp_path):
    datasets = []
    for index in range(3):
        path = tmp_path / f"dataset-{index}.geojson"
        _write_geojson(path, feature_id=f"asset-{index}")
        datasets.append(
            {
                "name": f"Dataset {index}",
                "input_path": str(path),
                "intended_use": "asset_handoff",
                "required_columns": ["asset_id"],
                "minimum_score": 100,
                "allowed_bands": ["ready"],
            }
        )
    manifest = tmp_path / "pilot.json"
    manifest.write_text(json.dumps({"datasets": datasets}), encoding="utf-8")

    payload = run_three_dataset_pilot(manifest, tmp_path / "pilot-output")

    assert payload["passed"] is True
    assert payload["dataset_count"] == 3
    assert all(row["acceptance_passed"] for row in payload["results"])
    assert (tmp_path / "pilot-output" / "pilot_results.json").exists()
