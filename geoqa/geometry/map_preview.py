from __future__ import annotations

from typing import Any

import geopandas as gpd
from shapely.geometry import mapping

from geoqa.models import Issue

DEFAULT_MAP_PREVIEW_LIMIT = 200


def build_map_preview(
    gdf: gpd.GeoDataFrame,
    issues: list[Issue],
    *,
    max_features: int = DEFAULT_MAP_PREVIEW_LIMIT,
) -> dict[str, Any]:
    """Build a browser-safe GeoJSON preview for the web map.

    The preview is intentionally sampled so large production datasets do not
    get pushed through the Vercel UI as full GeoJSON.
    """
    preview_gdf, crs_note = _to_lonlat(gdf)
    outlier_ids = {str(issue.feature_id) for issue in issues if issue.issue_code == "SPATIAL_OUTLIER" and issue.feature_id is not None}
    sample_indexes = list(preview_gdf.head(max_features).index)

    if outlier_ids and "feature_id" in preview_gdf.columns:
        for index, row in preview_gdf.iterrows():
            if str(row.get("feature_id")) in outlier_ids and index not in sample_indexes:
                sample_indexes.append(index)

    features: list[dict[str, Any]] = []
    for index in sample_indexes:
        row = preview_gdf.loc[index]
        geometry = row.geometry
        if geometry is None:
            continue
        try:
            if geometry.is_empty:
                continue
            feature_id = row.get("feature_id", index)
            is_outlier = str(feature_id) in outlier_ids
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "feature_id": _json_safe(feature_id),
                        "geometry_type": str(geometry.geom_type),
                        "preview_role": "spatial_outlier" if is_outlier else "sample",
                        "is_spatial_outlier": is_outlier,
                    },
                }
            )
        except Exception:
            continue

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "feature_count": int(len(gdf)),
            "preview_feature_count": len(features),
            "max_preview_features": max_features,
            "sampled": int(len(gdf)) > max_features,
            "outlier_feature_count": len(outlier_ids),
            "crs": "EPSG:4326",
            "source_crs_note": crs_note,
        },
    }


def _to_lonlat(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, str]:
    if gdf.crs:
        try:
            return gdf.to_crs("EPSG:4326"), f"Preview reprojected from {gdf.crs.to_string()} to EPSG:4326."
        except Exception:
            return gdf.copy(), "Preview uses source coordinates because reprojection to EPSG:4326 failed."
    return gdf.copy(), "Preview uses source coordinates because the dataset CRS is missing."


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
