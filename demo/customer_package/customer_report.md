# GeoQA Data Readiness Audit

## Executive Summary

GeoQA reviewed `Centreline Intersections Sample` for Demo City GIS Team.
The dataset contains 50 features and is classified as `needs_review` with a readiness score of `72/100`.

**Handoff decision:** Needs review before SQL/database loading.

GeoQA detected review-level findings that may be valid but should be confirmed before downstream use. Duplicate geometries should be reviewed before joins, reporting, or network workflows.

Customer notes: Assess readiness before SQL/database loading and downstream reporting.

## Intended Use

- Intended use: SQL/database loading
- Target CRS/SRID: `EPSG:4326`
- Required columns: OBJECTID

## Readiness Result

| Measure | Value |
| --- | --- |
| Readiness band | `needs_review` |
| Readiness score | `72/100` |
| High-priority findings | `1` |
| Medium-priority findings | `1` |
| Low-priority findings | `3` |
| Total findings | `5` |

## Geometry Profile

- Primary geometry: `Multi-point`
- Technical geometry type: `MultiPoint`
- Curved, circular, or arc geometry detected: `False`
- Multipart geometry present: `True`
- Z coordinates present: `False`

| Geometry Type | Plain-English Label | Count | Share |
| --- | --- | ---: | ---: |
| `MultiPoint` | Multi-point | `50` | `100.0%` |

## Spatial Anomalies

No strong spatial outliers were detected by the configured anomaly check.

## Critical Findings

- `[High]` `MISSING_REQUIRED_COLUMN`: Required column 'OBJECTID' is missing.
  Recommended action: Add the required schema column.
- `[Medium]` `DUPLICATE_GEOMETRY` for record `12`: Feature duplicates geometry of feature 11.
  Recommended action: Deduplicate repeated spatial features.
- `[Low]` `NULL_HEAVY_COLUMN`: Column 'ELEVATI12' is 98% null.
  Recommended action: Review whether sparse fields should be populated or removed.
- `[Low]` `NULL_HEAVY_COLUMN`: Column 'ELEVATI13' is 100% null.
  Recommended action: Review whether sparse fields should be populated or removed.
- `[Low]` `NULL_HEAVY_COLUMN`: Column 'HEIGHT_15' is 100% null.
  Recommended action: Review whether sparse fields should be populated or removed.

## Recommended Next Steps

- Review high-priority findings before production loading or handoff.
- Confirm spatial anomalies with the source system of record.
- Use `issues.csv` for record-level triage and assignment.
- Keep `summary.json`, `run_record.json`, and `geometry_profile.json` with the project audit trail.
- If findings are accepted as valid for the workflow, document the acceptance decision before downstream use.

## Included Evidence Package

- Customer report: `customer_report.md`
- Issue spreadsheet: `issues.csv`
- Deterministic QA report: `qa_report.md`
- Run summary: `summary.json`
- Run record: `run_record.json`
- Geometry profile: `geometry_profile.json`
- Customer intake: `customer_intake.json`