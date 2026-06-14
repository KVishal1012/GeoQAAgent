# Spatial Anomaly Playbook

Use this playbook when GeoQA reports spatial outlier records.

## What It Means

- A spatial outlier is a feature whose representative location is far outside the dataset's dominant spatial cluster.
- This can indicate a wrong coordinate, swapped latitude/longitude, wrong CRS, bad source record, or a legitimate remote asset.
- GeoQA should describe the feature as spatially unusual, not automatically wrong.

## Recommended Review Steps

- Check whether the source dataset is expected to cover multiple disconnected geographies.
- Verify the CRS/SRID and coordinate order for the outlier record.
- Compare the feature ID against the source system of record.
- Confirm whether the outlier belongs in a separate dataset, region, route, or asset group.
- If the feature is legitimate, document the reason before downstream loading or reporting.

## Safe Report Language

- "This feature is spatially unusual and should be reviewed."
- "This may indicate a CRS, coordinate order, or source-record issue, or it may be a legitimate remote asset."
- Do not state that the feature is invalid unless deterministic checks or source review prove it.
