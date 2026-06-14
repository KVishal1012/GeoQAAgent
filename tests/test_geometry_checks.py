import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from geoqa.checks.geometry_checks import run_geometry_checks
from geoqa.geometry.profile import build_geometry_profile


def test_geometry_checks_flags_mixed_types_and_duplicates():
    square = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["a", "b", "c"],
            "geometry": [square, square, LineString([(0, 0), (1, 1)])],
        },
        crs="EPSG:4326",
    )

    issues = run_geometry_checks(gdf)
    codes = {issue.issue_code for issue in issues}

    assert "MIXED_GEOMETRY_TYPES" in codes
    assert "DUPLICATE_GEOMETRY" in codes


def test_geometry_checks_flags_overlapping_polygons():
    left = Polygon([(0, 0), (0, 2), (2, 2), (2, 0)])
    right = Polygon([(1, 1), (1, 3), (3, 3), (3, 1)])
    gdf = gpd.GeoDataFrame(
        {"feature_id": ["left", "right"], "geometry": [left, right]},
        crs="EPSG:4326",
    )

    issues = run_geometry_checks(gdf)

    assert any(issue.issue_code == "OVERLAPPING_POLYGONS" for issue in issues)


def test_geometry_profile_describes_multiline_and_advanced_flags():
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["line-1", "line-2"],
            "geometry": [
                MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
                LineString([(4, 4, 1), (5, 5, 2)]),
            ],
        },
        crs="EPSG:4326",
    )

    profile = build_geometry_profile(gdf, source_geometry_types=["MultiLineString", "LineString"])

    assert profile["geometry_families"]["linear"] == 2
    assert profile["advanced_geometry_flags"]["multi_part"] is True
    assert profile["has_z"] is True
    labels = {item["label"] for item in profile["observed_geometry_types"]}
    assert "Multi-part line" in labels


def test_geometry_checks_flags_strong_spatial_outlier():
    cluster = [Point(-73.99 + (idx * 0.001), 40.75 + (idx * 0.001)) for idx in range(9)]
    outlier = Point(-97.51, 35.47)
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": [f"local-{idx}" for idx in range(9)] + ["remote-asset"],
            "geometry": cluster + [outlier],
        },
        crs="EPSG:4326",
    )

    issues = run_geometry_checks(gdf)
    outlier_issue = next(issue for issue in issues if issue.issue_code == "SPATIAL_OUTLIER")

    assert outlier_issue.feature_id == "remote-asset"
    assert outlier_issue.context["outlier_score"] > 8
    assert outlier_issue.context["method"] == "median_center_mad_with_extent_check"


def test_geometry_checks_does_not_flag_evenly_distributed_points_as_outliers():
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": [f"asset-{idx}" for idx in range(10)],
            "geometry": [Point(float(idx), 0.0) for idx in range(10)],
        },
        crs="EPSG:4326",
    )

    issues = run_geometry_checks(gdf)

    assert "SPATIAL_OUTLIER" not in {issue.issue_code for issue in issues}
