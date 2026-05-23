from __future__ import annotations

import geopandas as gpd


def normalize_crs(gdf: gpd.GeoDataFrame, target_crs: str | None = None) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    normalized = gdf.copy()
    if normalized.crs is None:
        notes.append("Dataset has no CRS; CRS-dependent checks will be limited.")
        return normalized, notes
    if target_crs and normalized.crs.to_string() != target_crs:
        normalized = normalized.to_crs(target_crs)
        notes.append(f"Reprojected dataset from {gdf.crs.to_string()} to {target_crs}.")
    else:
        notes.append(f"CRS retained as {normalized.crs.to_string()}.")
    return normalized, notes
