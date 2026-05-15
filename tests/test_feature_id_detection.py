import geopandas as gpd
from shapely.geometry import Point

from geoqa.runner import _ensure_feature_id


def test_ensure_feature_id_uses_existing_feature_id_column():
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["source-1", "source-2"],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )

    result, notes = _ensure_feature_id(gdf)

    assert result["feature_id"].tolist() == ["source-1", "source-2"]
    assert notes == ["Feature IDs retained from existing feature_id column."]


def test_ensure_feature_id_detects_common_object_id_column():
    gdf = gpd.GeoDataFrame(
        {
            "OBJECTID": [101, 102],
            "asset_id": ["asset-1", "asset-2"],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )

    result, notes = _ensure_feature_id(gdf)

    assert result["feature_id"].tolist() == [101, 102]
    assert notes == ["Feature IDs copied from source column 'OBJECTID'."]


def test_ensure_feature_id_detects_shapefile_truncated_id_column():
    gdf = gpd.GeoDataFrame(
        {
            "_id1": [201, 202],
            "OBJECTI20": [301, 302],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )

    result, notes = _ensure_feature_id(gdf)

    assert result["feature_id"].tolist() == [201, 202]
    assert notes == ["Feature IDs copied from source column '_id1'."]


def test_ensure_feature_id_generates_ids_when_candidate_is_not_unique():
    gdf = gpd.GeoDataFrame(
        {
            "OBJECTID": [101, 101],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )

    result, notes = _ensure_feature_id(gdf)

    assert result["feature_id"].tolist() == ["feature-0", "feature-1"]
    assert notes == ["Feature IDs generated because no complete unique ID column was detected."]

