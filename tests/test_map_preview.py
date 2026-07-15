from __future__ import annotations

import json

import geopandas as gpd
from shapely.geometry import Point

from geoqa.geometry.map_preview import build_map_preview
from geoqa.models import Issue
from geoqa.runner import run_geoqa


def test_map_preview_samples_features_and_keeps_outliers():
    gdf = gpd.GeoDataFrame(
        {"feature_id": [f"feature-{index}" for index in range(10)] + ["outlier"]},
        geometry=[Point(-79.4 + index * 0.001, 43.6) for index in range(10)] + [Point(-97.5, 35.5)],
        crs="EPSG:4326",
    )
    issue = Issue(
        issue_code="SPATIAL_OUTLIER",
        check_name="spatial_outlier",
        message="Feature is far outside the dataset cluster.",
        feature_id="outlier",
    )

    preview = build_map_preview(gdf, [issue], max_features=5)

    assert preview["type"] == "FeatureCollection"
    assert preview["metadata"]["sampled"] is True
    assert preview["metadata"]["preview_feature_count"] == 6
    roles = {feature["properties"]["feature_id"]: feature["properties"]["preview_role"] for feature in preview["features"]}
    assert roles["outlier"] == "spatial_outlier"


def test_run_geoqa_writes_map_preview_artifact(tmp_path):
    input_path = tmp_path / "points.geojson"
    gdf = gpd.GeoDataFrame(
        {"asset_id": ["a", "b", "c"]},
        geometry=[Point(-79.4, 43.6), Point(-79.41, 43.61), Point(-79.42, 43.62)],
        crs="EPSG:4326",
    )
    gdf.to_file(input_path, driver="GeoJSON")

    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])

    preview_path = result.artifact_paths["map_preview"]
    preview = json.loads(open(preview_path, encoding="utf-8").read())
    assert preview["type"] == "FeatureCollection"
    assert preview["metadata"]["feature_count"] == 3
    assert len(preview["features"]) == 3
