from __future__ import annotations

from itertools import combinations

import geopandas as gpd
import pandas as pd

from geoqa.models import Issue


def run_geometry_checks(gdf: gpd.GeoDataFrame, feature_id_column: str = "feature_id") -> list[Issue]:
    issues: list[Issue] = []
    geometry_types = {str(value) for value in gdf.geom_type.dropna().unique()}
    if len(geometry_types) > 1:
        issues.append(
            Issue(
                issue_code="MIXED_GEOMETRY_TYPES",
                check_name="geometry_type_consistency",
                message=f"Dataset contains mixed geometry types: {sorted(geometry_types)}",
            )
        )

    hashes: dict[bytes, str | int] = {}
    polygon_indices: list[int] = []

    for index, row in gdf.iterrows():
        geometry = row.geometry
        feature_id = row.get(feature_id_column, index)
        if geometry is None or pd.isna(geometry):
            issues.append(
                Issue(
                    issue_code="NULL_GEOMETRY",
                    check_name="null_geometry",
                    feature_id=feature_id,
                    message="Feature geometry is null.",
                )
            )
            continue
        if geometry.is_empty:
            issues.append(
                Issue(
                    issue_code="EMPTY_GEOMETRY",
                    check_name="empty_geometry",
                    feature_id=feature_id,
                    message="Feature geometry is empty.",
                )
            )
            continue
        if not geometry.is_valid:
            issues.append(
                Issue(
                    issue_code="INVALID_GEOMETRY",
                    check_name="geometry_validity",
                    feature_id=feature_id,
                    message="Feature geometry is invalid.",
                )
            )
        try:
            wkb = geometry.wkb
            if wkb in hashes:
                issues.append(
                    Issue(
                        issue_code="DUPLICATE_GEOMETRY",
                        check_name="duplicate_geometry",
                        feature_id=feature_id,
                        message=f"Feature duplicates geometry of feature {hashes[wkb]}.",
                    )
                )
            else:
                hashes[wkb] = feature_id
        except Exception:  # pragma: no cover - unusual geometry encoding failure
            pass

        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            polygon_indices.append(index)
            if geometry.area > 1_000_000_000:
                issues.append(
                    Issue(
                        issue_code="SUSPICIOUS_LARGE_FEATURE",
                        check_name="feature_size",
                        feature_id=feature_id,
                        message="Polygon area is suspiciously large for a QA input dataset.",
                    )
                )
            if 0 < geometry.area < 1e-10:
                issues.append(
                    Issue(
                        issue_code="SUSPICIOUS_SMALL_FEATURE",
                        check_name="feature_size",
                        feature_id=feature_id,
                        message="Polygon area is suspiciously small and may indicate precision issues.",
                    )
                )
        elif geometry.geom_type in {"LineString", "MultiLineString"} and geometry.length < 1e-9:
            issues.append(
                Issue(
                    issue_code="ZERO_LENGTH_LINE",
                    check_name="feature_length",
                    feature_id=feature_id,
                    message="Line feature length is effectively zero.",
                )
            )

    issues.extend(_find_polygon_overlaps(gdf, polygon_indices, feature_id_column))
    return issues


def _find_polygon_overlaps(
    gdf: gpd.GeoDataFrame,
    polygon_indices: list[int],
    feature_id_column: str,
) -> list[Issue]:
    issues: list[Issue] = []
    if len(polygon_indices) < 2:
        return issues
    for left_idx, right_idx in combinations(polygon_indices, 2):
        left = gdf.loc[left_idx]
        right = gdf.loc[right_idx]
        if left.geometry is None or right.geometry is None:
            continue
        if left.geometry.overlaps(right.geometry):
            issues.append(
                Issue(
                    issue_code="OVERLAPPING_POLYGONS",
                    check_name="polygon_overlap",
                    feature_id=left.get(feature_id_column, left_idx),
                    message=(
                        "Polygon overlaps with feature "
                        f"{right.get(feature_id_column, right_idx)}."
                    ),
                )
            )
    return issues
