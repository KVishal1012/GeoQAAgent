from __future__ import annotations

import geopandas as gpd

from geoqa.models import Issue


def run_schema_checks(
    gdf: gpd.GeoDataFrame,
    required_columns: list[str] | None = None,
    feature_id_column: str = "feature_id",
) -> list[Issue]:
    issues: list[Issue] = []
    required_columns = required_columns or []
    for column in required_columns:
        if column not in gdf.columns:
            issues.append(
                Issue(
                    issue_code="MISSING_REQUIRED_COLUMN",
                    check_name="required_columns",
                    message=f"Required column '{column}' is missing.",
                    context={"column": column},
                )
            )

    for column in gdf.columns:
        if column == gdf.geometry.name:
            continue
        if not isinstance(column, str):
            issues.append(
                Issue(
                    issue_code="NON_STRING_COLUMN_NAME",
                    check_name="column_names",
                    message=f"Column name '{column}' is not a string.",
                )
            )
            continue
        if len(column) > 128:
            issues.append(
                Issue(
                    issue_code="LONG_COLUMN_NAME",
                    check_name="column_names",
                    message=f"Column name '{column}' exceeds 128 characters.",
                    context={"column": column},
                )
            )
        null_ratio = float(gdf[column].isna().mean())
        if null_ratio >= 0.5:
            issues.append(
                Issue(
                    issue_code="NULL_HEAVY_COLUMN",
                    check_name="column_completeness",
                    message=f"Column '{column}' is {null_ratio:.0%} null.",
                    context={"column": column, "null_ratio": null_ratio},
                )
            )

    if feature_id_column in gdf.columns and gdf[feature_id_column].duplicated().any():
        issues.append(
            Issue(
                issue_code="DUPLICATE_FEATURE_ID",
                check_name="feature_id_uniqueness",
                message=f"Column '{feature_id_column}' contains duplicate values.",
                context={"column": feature_id_column},
            )
        )
    return issues
