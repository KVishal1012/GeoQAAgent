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


def test_streamlit_app_loads_existing_run_artifacts(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    result = streamlit_app.run_uploaded_dataset(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    streamlit_app.generate_agent_draft(result, use_static_demo=True)

    loaded = streamlit_app.load_run_artifacts(result.artifact_paths["output_dir"])

    assert loaded["summary"]["readiness"]["band"] == "ready"
    assert loaded["review_status"]["status"] == "draft_ready"



def test_streamlit_app_recent_runs_and_fix_plan_helpers(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(input_path)

    result = streamlit_app.run_uploaded_dataset(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    recent_runs = streamlit_app.load_recent_runs(str(tmp_path / "outputs"))
    fix_plan = streamlit_app.generate_fix_plan(result.artifact_paths["output_dir"])

    assert recent_runs
    assert recent_runs[0]["run_id"] == result.run_record.run_id
    assert Path(fix_plan["fix_plan_markdown"]).exists()


def test_streamlit_app_comparison_and_bundle_helpers(tmp_path):
    input_a = tmp_path / "a.geojson"
    input_b = tmp_path / "b.geojson"
    _write_geojson(input_a)
    _write_geojson(input_b)

    run_a = streamlit_app.run_uploaded_dataset(
        str(input_a),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    run_b = streamlit_app.run_uploaded_dataset(
        str(input_b),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )

    comparison = streamlit_app.compare_existing_runs(run_a.artifact_paths["output_dir"], run_b.artifact_paths["output_dir"])
    streamlit_app.generate_fix_plan(run_b.artifact_paths["output_dir"])
    bundle = streamlit_app.export_handoff(run_b.artifact_paths["output_dir"])

    assert Path(comparison["comparison_report"]).exists()
    assert Path(bundle["handoff_bundle"]).exists()
