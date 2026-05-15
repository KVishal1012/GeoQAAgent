import json
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
from shapely.geometry import Point

from geoqa.runner import run_geoqa


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
    for key in ("report", "issues_csv", "run_record", "summary"):
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
