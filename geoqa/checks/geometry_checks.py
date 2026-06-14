from __future__ import annotations

from itertools import combinations
from statistics import median

import geopandas as gpd
import pandas as pd

from geoqa.models import Issue

MIN_SPATIAL_OUTLIER_FEATURES = 8
SPATIAL_OUTLIER_SCORE_THRESHOLD = 8.0


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
    issues.extend(_find_spatial_outliers(gdf, feature_id_column))
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


def _find_spatial_outliers(gdf: gpd.GeoDataFrame, feature_id_column: str) -> list[Issue]:
    points: list[tuple[int, str | int, float, float]] = []
    for index, row in gdf.iterrows():
        geometry = row.geometry
        if geometry is None or pd.isna(geometry):
            continue
        try:
            if geometry.is_empty:
                continue
            point = geometry.representative_point()
            points.append((index, row.get(feature_id_column, index), float(point.x), float(point.y)))
        except Exception:
            continue

    if len(points) < MIN_SPATIAL_OUTLIER_FEATURES:
        return []

    xs = [point[2] for point in points]
    ys = [point[3] for point in points]
    center_x = float(median(xs))
    center_y = float(median(ys))
    distances = [_euclidean_distance(x, y, center_x, center_y) for _, _, x, y in points]
    median_distance = float(median(distances))
    deviations = [abs(distance - median_distance) for distance in distances]
    mad = float(median(deviations))
    if mad <= 0:
        non_zero = [distance for distance in distances if distance > 0]
        if not non_zero:
            return []
        mad = max(float(median(non_zero)) / 10, 1e-12)

    issues: list[Issue] = []
    for (index, feature_id, x, y), distance in zip(points, distances):
        score = 0.6745 * (distance - median_distance) / mad
        if score < SPATIAL_OUTLIER_SCORE_THRESHOLD:
            continue
        if not _expands_extent_strongly(points, index):
            continue
        issues.append(
            Issue(
                issue_code="SPATIAL_OUTLIER",
                check_name="spatial_outlier",
                feature_id=feature_id,
                message=(
                    "Feature is far outside the dataset's dominant spatial cluster "
                    "and should be reviewed."
                ),
                context={
                    "representative_x": round(x, 8),
                    "representative_y": round(y, 8),
                    "dataset_center_x": round(center_x, 8),
                    "dataset_center_y": round(center_y, 8),
                    "outlier_score": round(float(score), 2),
                    "distance_from_dataset_center": round(float(distance), 8),
                    "method": "median_center_mad_with_extent_check",
                },
            )
        )
    return issues


def _euclidean_distance(x: float, y: float, center_x: float, center_y: float) -> float:
    return ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5


def _expands_extent_strongly(points: list[tuple[int, str | int, float, float]], candidate_index: int) -> bool:
    all_xs = [point[2] for point in points]
    all_ys = [point[3] for point in points]
    remaining = [point for point in points if point[0] != candidate_index]
    if len(remaining) < MIN_SPATIAL_OUTLIER_FEATURES - 1:
        return False

    remaining_xs = [point[2] for point in remaining]
    remaining_ys = [point[3] for point in remaining]
    full_width = max(all_xs) - min(all_xs)
    full_height = max(all_ys) - min(all_ys)
    remaining_width = max(remaining_xs) - min(remaining_xs)
    remaining_height = max(remaining_ys) - min(remaining_ys)
    full_extent = max(full_width, full_height)
    remaining_extent = max(remaining_width, remaining_height, 1e-12)
    return full_extent / remaining_extent >= 5
