import geopandas as gpd
from shapely.geometry import Point

from geoqa.checks.schema_checks import run_schema_checks


def test_schema_checks_flags_missing_required_and_duplicate_ids():
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["dup", "dup"],
            "name": ["a", None],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )

    issues = run_schema_checks(gdf, required_columns=["asset_id"])
    codes = {issue.issue_code for issue in issues}

    assert "MISSING_REQUIRED_COLUMN" in codes
    assert "DUPLICATE_FEATURE_ID" in codes
    assert "NULL_HEAVY_COLUMN" in codes
