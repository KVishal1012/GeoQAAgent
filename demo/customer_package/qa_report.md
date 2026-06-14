# GeoQA Spatial Readiness Report

## Executive Summary

GeoQA inspected `centreline_intersections_sample.zip`, containing 50 features with MultiPoint geometry in EPSG:4326.

The dataset is classified as `needs_review` with a readiness score of `72/100`.

The most important finding is the presence of high-severity issues. These should be resolved before using the data in database loading, dashboard development, spatial joins, model execution, or downstream reporting.

- Status: `completed`
- Assessment ID: `geoqa-8b40f0b48eeb`

## Finding Summary

| Priority | Count | Meaning |
| --- | ---: | --- |
| High | `1` | Blocks reliable use until fixed |
| Medium | `1` | Needs review before handoff |
| Low | `3` | Cleanup or completeness concern |
| Total | `5` | All detected findings |


## Geometry Profile

| Geometry Type | Plain-English Label | Family | Count | Share |
| --- | --- | --- | ---: | ---: |
| `MultiPoint` | Multi-point | Point | `50` | `100.0%` |

- Primary geometry: `Multi-point`
- Multipart geometry present: `True`
- Geometry collections present: `False`
- Z coordinates present: `False`
- M coordinates present: `False`
- Curved, circular, or arc geometry detected: `False`
- Curve detection confidence: `not_detected_from_source_metadata`

- No curved or circular geometry was detected from available metadata.
- Length and area summaries should be reviewed carefully because the dataset uses geographic coordinates.

## Spatial Anomalies

No strong spatial outliers were detected by the configured anomaly check.

## Normalization Notes

- Feature IDs copied from source column '_id1'.
- CRS retained as EPSG:4326.
- No geometry normalization changes were required.
- Precision normalization skipped.

## Top Findings

- `[Medium]` `Duplicate Geometry` for record `12`: Feature duplicates geometry of feature 11.
  Suggested action: Deduplicate repeated spatial features.
- `[High]` `Missing Required Column`: Required column 'OBJECTID' is missing.
  Suggested action: Add the required schema column.
- `[Low]` `Null Heavy Column`: Column 'ELEVATI12' is 98% null.
  Suggested action: Review whether sparse fields should be populated or removed.
- `[Low]` `Null Heavy Column`: Column 'ELEVATI13' is 100% null.
  Suggested action: Review whether sparse fields should be populated or removed.
- `[Low]` `Null Heavy Column`: Column 'HEIGHT_15' is 100% null.
  Suggested action: Review whether sparse fields should be populated or removed.

## Business Value

- Converts geospatial QA from manual inspection into a repeatable run.
- Produces a readiness score that can be shared with data owners and downstream teams.
- Preserves feature-level IDs when available, making findings easier to trace back to source records.
- Writes machine-readable artifacts for audit, triage, and follow-up workflows.

## Output Files

- Output Dir: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb`
- Issues Csv: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/issues.csv`
- Run Record: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/run_record.json`
- Summary: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/summary.json`
- Geometry Profile: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/geometry_profile.json`
- Customer Intake: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/customer_intake.json`
- Customer Report: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/customer_report.md`
- Report: `/Volumes/Ultra Touch/Koushik's Laptop/Github/GeoQAAgent/demo/customer_package/runs/geoqa-8b40f0b48eeb/qa_report.md`
