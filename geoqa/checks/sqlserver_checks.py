from __future__ import annotations

import re

import geopandas as gpd

from geoqa.models import Issue

SQLSERVER_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def run_sqlserver_checks(gdf: gpd.GeoDataFrame) -> list[Issue]:
    issues: list[Issue] = []
    for column in gdf.columns:
        if column == gdf.geometry.name:
            continue
        if isinstance(column, str) and not SQLSERVER_COLUMN_RE.match(column):
            issues.append(
                Issue(
                    issue_code="SQLSERVER_INCOMPATIBLE_COLUMN_NAME",
                    check_name="sqlserver_column_compatibility",
                    message=f"Column '{column}' is not SQL Server friendly.",
                    context={"column": column},
                )
            )
    if gdf.crs is None:
        issues.append(
            Issue(
                issue_code="SQLSERVER_MISSING_SRID",
                check_name="sqlserver_srid",
                message="SQL Server spatial loading will need an explicit SRID because CRS is missing.",
            )
        )
    return issues
