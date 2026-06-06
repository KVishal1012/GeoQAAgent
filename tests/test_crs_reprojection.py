from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point
import pytest

from geoqa.normalization.crs_normalizer import normalize_crs, normalize_target_crs


def test_normalize_target_crs_accepts_plain_srid() -> None:
    assert normalize_target_crs("3857") == "EPSG:3857"
    assert normalize_target_crs("EPSG:4326") == "EPSG:4326"


def test_normalize_target_crs_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="Invalid target CRS/SRID"):
        normalize_target_crs("not-a-crs")


def test_normalize_crs_reprojects_when_target_differs() -> None:
    gdf = gpd.GeoDataFrame({"feature_id": ["a"]}, geometry=[Point(-79.38, 43.65)], crs="EPSG:4326")

    reprojected, notes = normalize_crs(gdf, target_crs="3857")

    assert reprojected.crs.to_string() == "EPSG:3857"
    assert any("Reprojected dataset from EPSG:4326 to EPSG:3857" in note for note in notes)
