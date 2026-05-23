from __future__ import annotations

import geopandas as gpd


def normalize_geometries(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    normalized = gdf.copy()

    invalid_mask = ~normalized.geometry.isna() & ~normalized.geometry.is_valid
    repaired = 0
    for idx in normalized.index[invalid_mask]:
        geometry = normalized.at[idx, normalized.geometry.name]
        fixed = _repair_geometry(geometry)
        if fixed is not None and not fixed.is_empty and fixed.is_valid:
            normalized.at[idx, normalized.geometry.name] = fixed
            repaired += 1
    if repaired:
        notes.append(f"Repaired {repaired} invalid geometries.")

    null_count = int(normalized.geometry.isna().sum())
    empty_count = int(normalized.geometry.is_empty.sum())
    if null_count:
        notes.append(f"Found {null_count} null geometries.")
    if empty_count:
        notes.append(f"Found {empty_count} empty geometries.")
    if not notes:
        notes.append("No geometry normalization changes were required.")
    return normalized, notes


def _repair_geometry(geometry):
    if geometry is None:
        return None
    make_valid = getattr(geometry, "make_valid", None)
    if callable(make_valid):
        return make_valid()
    try:
        return geometry.buffer(0)
    except Exception:  # pragma: no cover - defensive fallback
        return None
