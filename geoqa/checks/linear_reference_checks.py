from __future__ import annotations

import geopandas as gpd

from geoqa.models import Issue

REQUIRED_LRM_COLUMNS = {"route_id", "from_measure", "to_measure"}


def run_linear_reference_checks(gdf: gpd.GeoDataFrame) -> list[Issue]:
    issues: list[Issue] = []
    if not REQUIRED_LRM_COLUMNS.issubset(set(gdf.columns)):
        return issues

    missing_measure_rows = gdf[gdf["from_measure"].isna() | gdf["to_measure"].isna()]
    for index, row in missing_measure_rows.iterrows():
        issues.append(
            Issue(
                issue_code="MISSING_LINEAR_MEASURE",
                check_name="linear_reference_measures",
                feature_id=row.get("feature_id", index),
                message="Linear reference feature is missing from/to measure values.",
            )
        )

    reversed_rows = gdf[gdf["from_measure"] > gdf["to_measure"]]
    for index, row in reversed_rows.iterrows():
        issues.append(
            Issue(
                issue_code="REVERSED_LINEAR_MEASURE",
                check_name="linear_reference_measures",
                feature_id=row.get("feature_id", index),
                message="Linear reference feature has from_measure greater than to_measure.",
            )
        )
    return issues
