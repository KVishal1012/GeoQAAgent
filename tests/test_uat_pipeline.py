import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
from shapely.geometry import Point

from geoqa.llm.gateway import StaticLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.review.human_review import ReviewError, read_review_history, read_review_status
from geoqa.runner import run_geoqa
from geoqa.workflows import compare_run_outputs, export_handoff_bundle, generate_fix_plan_artifacts


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
            }
        ),
        encoding="utf-8",
    )


def _assert_standard_artifacts_exist(artifact_paths: dict[str, str]) -> None:
    for key in ("report", "issues_csv", "run_record", "summary", "geometry_profile"):
        assert Path(artifact_paths[key]).exists(), f"missing artifact: {key}"


def test_uat_clean_geojson_produces_ready_output(tmp_path):
    input_path = tmp_path / "clean.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1", "name": "First"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-2", "name": "Second"},
                "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
            },
        ],
    )

    result = run_geoqa(
        input_path=str(input_path),
        output_root=str(output_root),
        required_columns=["asset_id"],
    )

    assert result.run_record.status == "completed"
    assert result.run_record.readiness_score == 100
    assert result.run_record.readiness_band == "ready"
    assert result.issues == []
    assert result.summary["dataset"]["feature_count"] == 2
    assert result.summary["dataset"]["geometry_profile"]["primary_geometry_label"] == "Point"
    _assert_standard_artifacts_exist(result.artifact_paths)


def test_uat_problem_geojson_produces_actionable_findings(tmp_path):
    input_path = tmp_path / "problem.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-79.38, 43.65], [-79.38, 43.65]],
                },
            },
            {
                "type": "Feature",
                "properties": {"asset_id": None},
                "geometry": None,
            },
        ],
    )

    result = run_geoqa(
        input_path=str(input_path),
        output_root=str(output_root),
        required_columns=["asset_id", "route_id"],
    )
    issue_codes = {issue.issue_code for issue in result.issues}

    assert result.run_record.status == "completed"
    assert result.run_record.readiness_band == "not_ready"
    assert "MISSING_REQUIRED_COLUMN" in issue_codes
    assert "INVALID_GEOMETRY" in issue_codes
    assert "ZERO_LENGTH_LINE" in issue_codes
    assert "NULL_GEOMETRY" in issue_codes
    assert "NULL_HEAVY_COLUMN" in issue_codes
    _assert_standard_artifacts_exist(result.artifact_paths)


def test_uat_zipped_shapefile_input_is_accepted(tmp_path):
    shapefile_dir = tmp_path / "shapefile"
    shapefile_dir.mkdir()
    shapefile_path = shapefile_dir / "assets.shp"
    gdf = gpd.GeoDataFrame(
        {
            "asset_id": ["asset-1", "asset-2"],
            "geometry": [Point(-79.38, 43.65), Point(-79.39, 43.66)],
        },
        crs="EPSG:4326",
    )
    gdf.to_file(shapefile_path)

    zip_path = tmp_path / "assets.zip"
    with ZipFile(zip_path, "w") as archive:
        for component in shapefile_dir.iterdir():
            archive.write(component, arcname=component.name)

    result = run_geoqa(
        input_path=str(zip_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )

    assert result.run_record.status == "completed"
    assert result.run_record.readiness_score == 100
    assert result.run_record.readiness_band == "ready"
    assert result.summary["dataset"]["geometry_types"] == ["Point"]
    _assert_standard_artifacts_exist(result.artifact_paths)


def test_uat_detected_source_ids_are_used_in_findings(tmp_path):
    input_path = tmp_path / "source-ids.geojson"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 101, "asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
            {
                "type": "Feature",
                "properties": {"OBJECTID": 102, "asset_id": "asset-2"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
        ],
    )

    result = run_geoqa(
        input_path=str(input_path),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )

    duplicate_issue = next(issue for issue in result.issues if issue.issue_code == "DUPLICATE_GEOMETRY")
    assert duplicate_issue.feature_id == 102
    assert "Feature IDs copied from source column 'OBJECTID'." in result.run_record.normalization_notes


def test_uat_static_gateway_full_review_flow(tmp_path):
    input_path = tmp_path / "clean.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1", "name": "First"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-2", "name": "Second"},
                "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
            },
        ],
    )
    result = run_geoqa(
        input_path=str(input_path),
        output_root=str(output_root),
        required_columns=["asset_id"],
    )
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100. "
        "No QA findings were detected by the configured checks."
    )

    artifacts = generate_agent_report_artifacts(
        result,
        gateway=StaticLLMGateway(report_text),
        approve=True,
        reviewer_name="QA Reviewer",
        review_notes="UAT approval",
    )

    assert Path(artifacts["agent_report_draft"]).exists()
    assert Path(artifacts["agent_report"]).exists()
    review_status = read_review_status(result.artifact_paths["output_dir"])
    assert review_status is not None
    assert review_status.status == "approved"


def test_uat_blocked_agent_report_stays_unapproved(tmp_path):
    input_path = tmp_path / "clean.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1", "name": "First"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            }
        ],
    )
    result = run_geoqa(
        input_path=str(input_path),
        output_root=str(output_root),
        required_columns=["asset_id"],
    )
    report_text = "The dataset contains 999 features and is safe for routing."

    try:
        generate_agent_report_artifacts(
            result,
            gateway=StaticLLMGateway(report_text),
            approve=True,
            reviewer_name="QA Reviewer",
        )
    except ReviewError:
        pass
    else:
        raise AssertionError("Expected ReviewError for blocked agent report")

    review_status = read_review_status(result.artifact_paths["output_dir"])
    assert review_status is not None
    assert review_status.status == "blocked"
    history = read_review_history(result.artifact_paths["output_dir"])
    assert history[-1]["action"] == "blocked"
    assert not Path(result.artifact_paths["output_dir"], "agent_report.md").exists()


def test_uat_full_analyst_workflow(tmp_path):
    base_input = tmp_path / "base.geojson"
    target_input = tmp_path / "target.geojson"
    _write_geojson(
        base_input,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": None,
            }
        ],
    )
    _write_geojson(
        target_input,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-2"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
        ],
    )

    base_result = run_geoqa(
        input_path=str(base_input),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    target_result = run_geoqa(
        input_path=str(target_input),
        output_root=str(tmp_path / "outputs"),
        required_columns=["asset_id"],
    )
    report_text = (
        "GeoQA inspected target.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 93/100. "
        "The `DUPLICATE_GEOMETRY` finding should be reviewed before downstream use."
    )
    generate_agent_report_artifacts(
        target_result,
        gateway=StaticLLMGateway(report_text),
        approve=True,
        reviewer_name="QA Reviewer",
        review_notes="Approved for handoff",
    )
    fix_plan = generate_fix_plan_artifacts(target_result.artifact_paths["output_dir"])
    comparison = compare_run_outputs(base_result.artifact_paths["output_dir"], target_result.artifact_paths["output_dir"])
    bundle = export_handoff_bundle(
        target_result.artifact_paths["output_dir"],
        comparison_key=comparison["comparison_key"],
    )

    assert Path(fix_plan["fix_plan_markdown"]).exists()
    assert Path(comparison["comparison_report"]).exists()
    assert Path(bundle["handoff_bundle"]).exists()
