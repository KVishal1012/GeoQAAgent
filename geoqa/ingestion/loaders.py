from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd

from .validators import ValidationError


def load_dataset(path: str | Path) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    file_path = Path(path).expanduser().resolve()
    read_path: str | Path = file_path
    if file_path.suffix.lower() == ".zip":
        read_path = f"zip://{file_path}"
    try:
        gdf = gpd.read_file(read_path)
    except Exception as exc:  # pragma: no cover - exercised in integration usage
        raise ValidationError(f"Unable to read geospatial file: {exc}") from exc
    if gdf.empty:
        raise ValidationError("Dataset contains zero features.")
    if gdf.geometry.name not in gdf.columns:
        raise ValidationError("Dataset does not contain a geometry column.")
    metadata = {
        "filename": file_path.name,
        "source_path": str(file_path),
        "feature_count": int(len(gdf)),
        "geometry_types": sorted({str(geom_type) for geom_type in gdf.geom_type.dropna().unique()}),
        "crs": gdf.crs.to_string() if gdf.crs else None,
        "columns": [str(column) for column in gdf.columns],
    }
    return gdf, metadata
