from __future__ import annotations

from collections import Counter
from typing import Any

import geopandas as gpd
from shapely.geometry.base import BaseGeometry


GEOMETRY_LABELS = {
    "Point": ("point", "Point"),
    "MultiPoint": ("point", "Multi-point"),
    "LineString": ("linear", "Line"),
    "MultiLineString": ("linear", "Multi-part line"),
    "LinearRing": ("linear", "Linear ring"),
    "Polygon": ("polygon", "Polygon"),
    "MultiPolygon": ("polygon", "Multi-part polygon"),
    "GeometryCollection": ("collection", "Geometry collection"),
    "CircularString": ("curve_or_circular", "Circular line"),
    "CompoundCurve": ("curve_or_circular", "Compound curve"),
    "CurvePolygon": ("curve_or_circular", "Curved polygon"),
    "MultiCurve": ("curve_or_circular", "Multi-curve"),
    "MultiSurface": ("curve_or_circular", "Multi-surface"),
}

CURVE_TERMS = ("curve", "circular", "arc")


def build_geometry_profile(
    gdf: gpd.GeoDataFrame,
    source_geometry_types: list[str] | None = None,
) -> dict[str, Any]:
    """Build a reader-friendly deterministic profile of geometry structure."""

    source_types = [str(value) for value in source_geometry_types or [] if value]
    observed_counts = Counter(str(value) for value in gdf.geom_type.dropna())
    geometry_type_rows = []
    family_counts = {
        "point": 0,
        "linear": 0,
        "polygon": 0,
        "collection": 0,
        "curve_or_circular": 0,
        "unknown": 0,
    }
    feature_total = max(int(len(gdf)), 1)

    for geometry_type, count in sorted(observed_counts.items()):
        family, label = _classify_geometry_type(geometry_type)
        family_counts[family] = family_counts.get(family, 0) + int(count)
        geometry_type_rows.append(
            {
                "type": geometry_type,
                "label": label,
                "family": family,
                "count": int(count),
                "percent": round((int(count) / feature_total) * 100, 2),
            }
        )

    null_count = int(gdf.geometry.isna().sum())
    empty_count = int(gdf.geometry.apply(lambda geometry: bool(geometry is not None and getattr(geometry, 'is_empty', False))).sum())
    advanced_flags = _advanced_geometry_flags(gdf)
    total_bounds = _safe_total_bounds(gdf)

    curve_status = _curve_detection_status(source_types, observed_counts.keys())
    return {
        "observed_geometry_types": geometry_type_rows,
        "geometry_families": family_counts,
        "source_geometry_types": source_types,
        "primary_geometry_type": geometry_type_rows[0]["type"] if len(geometry_type_rows) == 1 else "mixed" if geometry_type_rows else "unknown",
        "primary_geometry_label": geometry_type_rows[0]["label"] if len(geometry_type_rows) == 1 else "Mixed geometry" if geometry_type_rows else "Unknown geometry",
        "null_geometry_count": null_count,
        "empty_geometry_count": max(empty_count, 0),
        "total_bounds": total_bounds,
        "has_z": advanced_flags["z_coordinates"],
        "has_m": advanced_flags["m_coordinates"],
        "has_curves_or_arcs": curve_status["detected"],
        "curve_detection_confidence": curve_status["confidence"],
        "advanced_geometry_flags": advanced_flags,
        "unique_features": _unique_feature_summary(gdf),
        "notes": _profile_notes(gdf, curve_status),
    }


def _classify_geometry_type(geometry_type: str) -> tuple[str, str]:
    if geometry_type in GEOMETRY_LABELS:
        return GEOMETRY_LABELS[geometry_type]
    lowered = geometry_type.lower()
    if any(term in lowered for term in CURVE_TERMS):
        return "curve_or_circular", geometry_type.replace("_", " ").title()
    return "unknown", geometry_type.replace("_", " ").title()


def _advanced_geometry_flags(gdf: gpd.GeoDataFrame) -> dict[str, bool]:
    flags = {
        "geometry_collection": False,
        "multi_part": False,
        "holes_or_interior_rings": False,
        "multipart_polygons": False,
        "z_coordinates": False,
        "m_coordinates": False,
    }
    for geometry in _iter_geometries(gdf):
        geometry_type = geometry.geom_type
        flags["geometry_collection"] = flags["geometry_collection"] or geometry_type == "GeometryCollection"
        flags["multi_part"] = flags["multi_part"] or geometry_type.startswith("Multi")
        flags["multipart_polygons"] = flags["multipart_polygons"] or geometry_type == "MultiPolygon"
        flags["z_coordinates"] = flags["z_coordinates"] or _has_coordinate_dimension(geometry, "has_z")
        flags["m_coordinates"] = flags["m_coordinates"] or _has_coordinate_dimension(geometry, "has_m")
        flags["holes_or_interior_rings"] = flags["holes_or_interior_rings"] or _interior_ring_count(geometry) > 0
    return flags


def _unique_feature_summary(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    duplicate_count = 0
    seen_wkb: set[bytes] = set()
    point_coordinates: set[tuple[float, float]] = set()
    multipart_count = 0
    interior_ring_count = 0

    for geometry in _iter_geometries(gdf):
        try:
            wkb = geometry.wkb
            if wkb in seen_wkb:
                duplicate_count += 1
            else:
                seen_wkb.add(wkb)
        except Exception:  # pragma: no cover - unusual geometry encoding failure
            pass

        if geometry.geom_type.startswith("Multi"):
            multipart_count += 1
        interior_ring_count += _interior_ring_count(geometry)
        if geometry.geom_type == "Point":
            point_coordinates.add((round(float(geometry.x), 12), round(float(geometry.y), 12)))

    return {
        "duplicate_geometry_count": duplicate_count,
        "multipart_feature_count": multipart_count,
        "features_with_polygon_holes": _features_with_holes(gdf),
        "total_polygon_hole_count": interior_ring_count,
        "unique_point_coordinate_count": len(point_coordinates),
    }


def _curve_detection_status(source_types: list[str], observed_types: Any) -> dict[str, Any]:
    all_types = [*source_types, *[str(value) for value in observed_types]]
    detected = any(any(term in geometry_type.lower() for term in CURVE_TERMS) for geometry_type in all_types)
    if detected:
        confidence = "detected"
    elif source_types:
        confidence = "not_detected_from_source_metadata"
    else:
        confidence = "unknown"
    return {"detected": detected, "confidence": confidence}


def _profile_notes(gdf: gpd.GeoDataFrame, curve_status: dict[str, Any]) -> list[str]:
    notes = []
    if curve_status["confidence"] == "unknown":
        notes.append("Curved or circular geometry detection depends on source metadata and may not be available after loading.")
    elif not curve_status["detected"]:
        notes.append("No curved or circular geometry was detected from available metadata.")
    if gdf.crs and getattr(gdf.crs, "is_geographic", False):
        notes.append("Length and area summaries should be reviewed carefully because the dataset uses geographic coordinates.")
    return notes


def _safe_total_bounds(gdf: gpd.GeoDataFrame) -> dict[str, float] | None:
    try:
        min_x, min_y, max_x, max_y = gdf.total_bounds
    except Exception:
        return None
    values = [min_x, min_y, max_x, max_y]
    if any(value != value for value in values):
        return None
    return {"min_x": float(min_x), "min_y": float(min_y), "max_x": float(max_x), "max_y": float(max_y)}


def _iter_geometries(gdf: gpd.GeoDataFrame):
    for geometry in gdf.geometry:
        if geometry is None:
            continue
        try:
            if geometry.is_empty:
                continue
        except Exception:
            continue
        yield geometry


def _has_coordinate_dimension(geometry: BaseGeometry, attribute: str) -> bool:
    try:
        return bool(getattr(geometry, attribute, False))
    except Exception:
        return False


def _interior_ring_count(geometry: BaseGeometry) -> int:
    if geometry.geom_type == "Polygon":
        return len(getattr(geometry, "interiors", []))
    if geometry.geom_type == "MultiPolygon":
        return sum(len(getattr(part, "interiors", [])) for part in geometry.geoms)
    return 0


def _features_with_holes(gdf: gpd.GeoDataFrame) -> int:
    return sum(1 for geometry in _iter_geometries(gdf) if _interior_ring_count(geometry) > 0)
