from __future__ import annotations

import geopandas as gpd

from geoqa.models import Issue


def run_crs_checks(gdf: gpd.GeoDataFrame) -> list[Issue]:
    issues: list[Issue] = []
    if gdf.crs is None:
        issues.append(
            Issue(
                issue_code="MISSING_CRS",
                check_name="crs_presence",
                message="Dataset does not define a coordinate reference system.",
            )
        )
        return issues

    crs_string = gdf.crs.to_string()
    if "4326" in crs_string or "4269" in crs_string:
        bounds = gdf.total_bounds
        minx, miny, maxx, maxy = bounds
        if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
            issues.append(
                Issue(
                    issue_code="OUT_OF_RANGE_COORDINATES",
                    check_name="coordinate_plausibility",
                    message="Geographic CRS coordinates fall outside valid longitude/latitude bounds.",
                )
            )
    return issues
