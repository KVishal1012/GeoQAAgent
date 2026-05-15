import geopandas as gpd
from shapely.geometry import LineString, Polygon

from geoqa.checks.geometry_checks import run_geometry_checks


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
