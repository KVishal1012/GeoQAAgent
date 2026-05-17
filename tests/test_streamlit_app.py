import json
from pathlib import Path

import streamlit_app


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


def test_streamlit_app_runs_dataset_and_generates_reviewable_draft(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    result = streamlit_app.run_uploaded_dataset(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    artifacts = streamlit_app.generate_agent_draft(result, use_static_demo=True)
    loaded = streamlit_app.load_run_artifacts(result.artifact_paths["output_dir"])

    assert Path(artifacts["agent_report_draft"]).exists()
    assert loaded["review_status"]["status"] == "draft_ready"
    assert "GeoQA inspected" in loaded["agent_report_draft"]


def test_streamlit_app_review_helpers_handle_approval_and_rejection(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    result = streamlit_app.run_uploaded_dataset(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    streamlit_app.generate_agent_draft(result, use_static_demo=True)

    rejected = streamlit_app.review_agent_output(
        result.artifact_paths["output_dir"],
        action="reject",
        reviewer_name="QA Reviewer",
        notes="Needs edits",
    )
    assert rejected["review_status_payload"]["status"] == "rejected"

    approved = streamlit_app.review_agent_output(
        result.artifact_paths["output_dir"],
        action="approve",
        reviewer_name="QA Reviewer",
        notes="Approved after edits",
    )
    assert approved["review_status_payload"]["status"] == "approved"
    assert Path(approved["agent_report"]).exists()
