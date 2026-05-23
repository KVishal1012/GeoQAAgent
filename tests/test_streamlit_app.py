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
    assert loaded["issue_filters"]["total_rows"] == 0


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
    streamlit_app.generate_agent_draft(run_b, use_static_demo=True)
    streamlit_app.generate_fix_plan(run_b.artifact_paths["output_dir"])
    comparison = streamlit_app.compare_existing_runs(run_a.artifact_paths["output_dir"], run_b.artifact_paths["output_dir"])
    bundle = streamlit_app.export_handoff(run_b.artifact_paths["output_dir"], comparison_key=comparison["comparison_key"])

    assert Path(comparison["comparison_report"]).exists()
    assert Path(bundle["handoff_bundle"]).exists()


def test_streamlit_app_issue_filters_and_paged_rows(tmp_path):
    input_path = tmp_path / "problem.geojson"
    input_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"asset_id": None},
                        "geometry": None,
                    },
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-2"},
                        "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-3"},
                        "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = streamlit_app.run_uploaded_dataset(
        str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    filters = streamlit_app.load_issue_filter_options(result.artifact_paths["output_dir"])
    page = streamlit_app.load_issue_rows_page(
        result.artifact_paths["output_dir"],
        issue_code="DUPLICATE_GEOMETRY",
        limit=1,
        offset=0,
    )

    assert filters["issue_code_counts"]["DUPLICATE_GEOMETRY"] == 1
    assert page["total_rows"] == 1
    assert len(page["rows"]) == 1


def test_streamlit_display_helpers_use_plain_english_labels():
    recent_runs = streamlit_app.format_recent_runs_for_display(
        [
            {
                "run_id": "geoqa-123",
                "dataset_name": "roads.geojson",
                "finished_at": "2026-05-23T10:00:00Z",
                "readiness_band": "needs_review",
                "readiness_score": 87,
                "review_status": "draft_ready",
                "issue_counts": {"high": 0, "medium": 1, "low": 2, "total": 3},
                "output_dir": "/tmp/run",
            }
        ]
    )
    issue_rows = streamlit_app.format_issue_rows_for_display(
        [
            {
                "severity": "medium",
                "issue_code": "DUPLICATE_GEOMETRY",
                "feature_id": "A-101",
                "message": "Duplicate point found.",
                "suggested_fix": "Review duplicate records.",
                "context": {"column": "asset_id", "count": 2},
            }
        ]
    )
    comparisons = streamlit_app.format_comparisons_for_display(
        [
            {
                "comparison_key": "against_geoqa-100",
                "generated_at": "2026-05-23T10:05:00Z",
                "base_run_id": "geoqa-100",
                "target_run_id": "geoqa-123",
                "summary_path": "/tmp/summary.json",
                "report_path": "/tmp/report.md",
            }
        ]
    )

    assert set(recent_runs[0]) >= {"Dataset", "Readiness", "Review Status", "Total Issues", "Output Folder"}
    assert recent_runs[0]["Review Status"] == "Draft Ready"
    assert set(issue_rows[0]) == {"Severity", "Finding Type", "Record ID", "Finding Details", "Suggested Action", "Evidence"}
    assert issue_rows[0]["Finding Type"] == "Duplicate Geometry"
    assert "Column: asset_id" in issue_rows[0]["Evidence"]
    assert set(comparisons[0]) == {"Comparison", "Generated At", "Baseline Run", "Compared Run", "Summary File", "Report File"}
