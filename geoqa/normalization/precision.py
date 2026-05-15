from __future__ import annotations

import geopandas as gpd
from shapely import set_precision


def normalize_precision(
    gdf: gpd.GeoDataFrame,
    grid_size: float | None = None,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    if not grid_size:
        return gdf.copy(), ["Precision normalization skipped."]
    normalized = gdf.copy()
    normalized.geometry = normalized.geometry.apply(
        lambda geom: None if geom is None else set_precision(geom, grid_size)
    )
    return normalized, [f"Applied coordinate precision grid size {grid_size}."]
