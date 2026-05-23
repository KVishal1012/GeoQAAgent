# GeoQA Spatial Readiness Report

## Executive Summary

GeoQA inspected `centreline_intersections_sample.zip`, containing 50 features with MultiPoint geometry in EPSG:4326.

The dataset is classified as `needs_review` with a readiness score of `87/100`.

The most important finding is a duplicate geometry record. This may be valid for intersection datasets in some workflows, but it should be reviewed before using the data in spatial joins, network analysis, SQL Server loading, or downstream reporting.

- Status: `completed`
- Assessment ID: `demo-centreline-v011`

## Finding Summary

| Priority | Count | Meaning |
| --- | ---: | --- |
| High | `0` | Blocks reliable use until fixed |
| Medium | `1` | Needs review before handoff |
| Low | `3` | Cleanup or completeness concern |
| Total | `4` | All detected findings |

## Normalization Notes

- Feature IDs copied from source column '_id1'.
- CRS retained as EPSG:4326.
- No geometry normalization changes were required.
- Precision normalization skipped.

## Top Findings

- `[medium]` `Duplicate Geometry` record `12`: Feature duplicates geometry of record 11.
  Suggested fix: Deduplicate repeated spatial features.
- `[low]` `Null Heavy Column`: Column 'ELEVATI12' is 98% null.
  Suggested fix: Review whether sparse fields should be populated or removed.
- `[low]` `Null Heavy Column`: Column 'ELEVATI13' is 100% null.
  Suggested fix: Review whether sparse fields should be populated or removed.
- `[low]` `Null Heavy Column`: Column 'HEIGHT_15' is 100% null.
  Suggested fix: Review whether sparse fields should be populated or removed.

## Business Value

- Converts geospatial QA from manual inspection into a repeatable run.
- Produces a readiness score that can be shared with data owners and downstream teams.
- Preserves feature-level IDs when available, making findings easier to trace back to source records.
- Writes machine-readable artifacts for audit, triage, and follow-up workflows.

## Output Files

- Output Directory: `demo/output`
- Issues Csv: `demo/output/issues.csv`
- Run Record: `demo/output/run_record.json`
- Summary: `demo/output/summary.json`
- Report: `demo/output/qa_report.md`
