from __future__ import annotations

import geopandas as gpd
from pyproj import CRS


def normalize_target_crs(target_crs: str | int | None) -> str | None:
    if target_crs is None:
        return None
    raw_value = str(target_crs).strip()
    if not raw_value:
        return None
    if raw_value.isdigit():
        raw_value = f"EPSG:{raw_value}"
    try:
        return CRS.from_user_input(raw_value).to_string()
    except Exception as exc:
        raise ValueError(f"Invalid target CRS/SRID: {target_crs}") from exc


def normalize_crs(gdf: gpd.GeoDataFrame, target_crs: str | None = None) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    normalized = gdf.copy()
    normalized_target = normalize_target_crs(target_crs)
    if normalized.crs is None:
        if normalized_target:
            notes.append(f"Dataset has no source CRS; target reprojection to {normalized_target} was not applied.")
        else:
            notes.append("Dataset has no CRS; CRS-dependent checks will be limited.")
        return normalized, notes
    if normalized_target and CRS.from_user_input(normalized.crs) != CRS.from_user_input(normalized_target):
        normalized = normalized.to_crs(normalized_target)
        notes.append(f"Reprojected dataset from {gdf.crs.to_string()} to {normalized_target}.")
    else:
        notes.append(f"CRS retained as {normalized.crs.to_string()}.")
    return normalized, notes
