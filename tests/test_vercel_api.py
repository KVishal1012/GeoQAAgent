from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

from api.index import app
from geoqa.production.worker import process_next_run


def _write_geojson(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-1"},
                        "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-2"},
                        "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _poll_run(client, run_id: str, headers: dict[str, str], timeout_seconds: float = 10.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}", headers=headers)
        payload = response.get_json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.1)
    raise AssertionError(f"Run {run_id} did not complete within {timeout_seconds}s")


def test_vercel_api_health_and_config_are_public(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.delenv("GEOQA_API_KEY", raising=False)

    client = app.test_client()

    health = client.get("/health")
    config = client.get("/config")

    assert health.status_code == 200
    assert health.get_json()["status"] == "healthy"
    assert config.status_code == 200
    assert "request_id" in config.get_json()


def test_vercel_root_renders_operator_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.delenv("GEOQA_API_KEY", raising=False)

    client = app.test_client()

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    assert "GeoQA Data Readiness Audit" in body
    assert "Evidence Package Console" in body
    assert "New run" in body
    assert "Spatial evidence" in body
    assert "Customer report PDF" in body
    assert "Issues CSV" in body
    assert "Handoff bundle" in body
    assert "Approve package" in body
    assert "Target CRS / SRID" in body
    assert "EPSG:3857" in body
    assert 'type="file"' in body


def test_vercel_root_prioritizes_revenue_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))

    client = app.test_client()
    body = client.get("/").get_data(as_text=True)

    assert 'primaryArtifactOrder = ["customer_report_pdf", "issues_csv", "handoff_bundle"]' in body
    assert 'customer_report_pdf: "Customer report PDF"' in body
    assert 'issues_csv: "Issues CSV"' in body
    assert 'handoff_bundle: "Handoff bundle"' in body
    assert 'qa_report: "QA report"' in body
    assert 'summary: "Summary JSON"' in body
    assert 'geometry_profile: "Geometry profile JSON"' in body


def test_vercel_root_contains_review_ui_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))

    client = app.test_client()
    body = client.get("/").get_data(as_text=True)

    assert "reviewerName" in body
    assert "reviewNotes" in body
    assert "approvePackage" in body
    assert "rejectPackage" in body
    assert "async function reviewRun(action)" in body
    assert "/api/v1/runs/${currentRunId}/review" in body


def test_vercel_root_uses_resumable_supabase_upload_for_large_files(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))

    client = app.test_client()
    body = client.get("/").get_data(as_text=True)

    assert "tus-js-client" in body
    assert "upload/resumable" not in body  # endpoint comes from the upload-session API, not hardcoded UI state
    assert "x-signature" not in body
    assert "uploadLargeFileWithTus" in body
    assert "session.resumable_upload" in body
    assert "resumable_headers" in body
    assert "session.upload_url" in body
    assert "Uploading large file to Supabase Storage" in body


def test_vercel_api_requires_api_key_for_v1_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")

    client = app.test_client()

    denied = client.post("/api/v1/runs", json={"input_path": "missing.geojson"})
    assert denied.status_code == 401
    assert denied.get_json()["error"]["code"] == "unauthorized"


def test_vercel_api_create_run_and_fetch_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")

    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"input_path": str(input_path), "required_columns": ["asset_id"]},
    )
    assert created.status_code == 202
    created_payload = created.get_json()
    assert created_payload["status"] == "queued"
    assert "run_id" in created_payload
    assert "request_id" in created_payload

    run_payload = _poll_run(client, created_payload["run_id"], headers=headers)
    assert run_payload["status"] == "completed"
    assert run_payload["readiness_band"] == "ready"

    artifacts = client.get(f"/api/v1/runs/{created_payload['run_id']}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    artifacts_payload = artifacts.get_json()
    assert artifacts_payload["artifacts"]["qa_report"]["exists"] is True
    assert artifacts_payload["artifacts"]["summary"]["exists"] is True


def test_vercel_api_review_requires_completed_agent_draft(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")

    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"input_path": str(input_path), "required_columns": ["asset_id"]},
    )
    run_id = created.get_json()["run_id"]

    _poll_run(client, run_id, headers=headers)

    review = client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=headers,
        json={"action": "approve", "reviewer_name": "QA Reviewer"},
    )

    # No agent draft was generated for this run, so review fails with a stable envelope.
    assert review.status_code == 409
    payload = review.get_json()
    assert payload["error"]["code"] == "review_failed"
    assert "request_id" in payload


def test_vercel_api_rejects_invalid_target_srid(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")

    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    client = app.test_client()
    response = client.post(
        "/api/v1/runs",
        headers={"x-api-key": "test-key"},
        json={"input_path": str(input_path), "target_srid": "not-a-srid"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"
    assert response.get_json()["error"]["details"]["field"] == "target_crs"


def test_vercel_api_error_envelope_for_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")

    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    response = client.post("/api/v1/runs", headers=headers, json={})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]["field"] == "input_path"
    assert "request_id" in payload



def test_vercel_upload_rejects_unsupported_file_type(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    client = app.test_client()
    response = client.post(
        "/api/v1/uploads",
        headers={"x-api-key": "test-key"},
        data={"file": (io.BytesIO(b"not spatial"), "notes.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "production_store_error"
    assert "Unsupported file type" in response.get_json()["error"]["message"]


def test_vercel_upload_run_worker_and_artifact_download(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    source = tmp_path / "uploaded.geojson"
    _write_geojson(source)

    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    upload = client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"file": (io.BytesIO(source.read_bytes()), "uploaded.geojson")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    upload_payload = upload.get_json()
    assert upload_payload["upload_id"].startswith("upload-")

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={
            "upload_id": upload_payload["upload_id"],
            "upload_storage_path": upload_payload["storage_path"],
            "filename": upload_payload["filename"],
            "required_columns": ["asset_id"],
            "target_srid": "3857",
            "customer_intake": {"customer_name": "City GIS Team", "dataset_name": "Revenue Demo", "intended_use": "sql_load"},
        },
    )
    assert created.status_code == 202
    run_id = created.get_json()["run_id"]

    queued = client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert queued.get_json()["status"] == "queued"

    processed = process_next_run()
    assert processed is not None
    assert processed["run_id"] == run_id
    assert processed["status"] == "completed"

    completed = client.get(f"/api/v1/runs/{run_id}", headers=headers)
    completed_payload = completed.get_json()
    assert completed_payload["status"] == "completed"
    assert completed_payload["readiness_band"] == "ready"
    assert completed_payload["target_crs"] == "EPSG:3857"

    artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts", headers=headers)
    artifact_payload = artifacts.get_json()
    assert artifact_payload["artifacts"]["qa_report"]["exists"] is True
    assert artifact_payload["artifacts"]["issues_csv"]["exists"] is True
    assert artifact_payload["artifacts"]["customer_report"]["exists"] is True
    assert artifact_payload["artifacts"]["customer_report_pdf"]["exists"] is True
    assert artifact_payload["artifacts"]["customer_intake"]["exists"] is True
    assert artifact_payload["artifacts"]["qa_report"]["url"].endswith("/qa_report/download")

    report = client.get(f"/api/v1/runs/{run_id}/artifacts/qa_report/download", headers=headers)
    assert report.status_code == 200
    assert b"GeoQA Spatial Readiness Report" in report.data

    customer_report = client.get(f"/api/v1/runs/{run_id}/artifacts/customer_report/download", headers=headers)
    assert customer_report.status_code == 200
    assert b"GeoQA Data Readiness Audit" in customer_report.data

    customer_pdf = client.get(f"/api/v1/runs/{run_id}/artifacts/customer_report_pdf/download", headers=headers)
    assert customer_pdf.status_code == 200
    assert customer_pdf.data[:4] == b"%PDF"


def test_vercel_upload_init_and_complete_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    client = app.test_client()
    headers = {"x-api-key": "test-key"}

    init = client.post(
        "/api/v1/uploads/init",
        headers=headers,
        json={"filename": "roads.geojson", "size_bytes": 128, "content_type": "application/geo+json"},
    )
    assert init.status_code == 201
    session = init.get_json()
    assert session["direct_upload"] is False
    assert session["fallback_upload_url"] == "/api/v1/uploads"

    complete = client.post(
        "/api/v1/uploads/complete",
        headers=headers,
        json={
            "upload_id": session["upload_id"],
            "filename": session["filename"],
            "storage_path": session["storage_path"],
            "size_bytes": session["size_bytes"],
            "content_type": session["content_type"],
        },
    )
    assert complete.status_code == 200
    assert complete.get_json()["upload_completed_at"]


def test_vercel_config_exposes_v11_runtime_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("GEOQA_LARGE_FILE_MODE", "true")
    monkeypatch.setenv("GEOQA_LARGE_FILE_MAX_UPLOAD_MB", "1024")
    monkeypatch.setenv("GEOQA_WORKER_STALE_AFTER_SECONDS", "30")
    monkeypatch.setenv("GEOQA_WORKER_MAX_ATTEMPTS", "4")

    client = app.test_client()
    response = client.get("/config")
    payload = response.get_json()

    assert payload["large_file_mode"] is True
    assert payload["large_file_max_upload_mb"] == 1024
    assert payload["active_max_upload_mb"] == 1024
    assert payload["worker_stale_after_seconds"] == 30
    assert payload["worker_max_attempts"] == 4


def test_vercel_runtime_upload_init_uses_tmp_fallback(monkeypatch):
    monkeypatch.delenv("GEOQA_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    client = app.test_client()
    response = client.post(
        "/api/v1/uploads/init",
        json={"filename": "roads.geojson", "size_bytes": 128, "content_type": "application/geo+json"},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["direct_upload"] is False
    assert "geoqa-outputs/production_mvp/uploads" in payload["storage_path"]
