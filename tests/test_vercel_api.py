from __future__ import annotations

import json
import os
import time
from pathlib import Path

from api.index import app


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
