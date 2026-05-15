# GeoQA Spatial Readiness Report

## Executive Summary

GeoQA inspected `centreline_intersections_sample.zip`, containing 50 features with MultiPoint geometry in EPSG:4326.

The dataset is classified as `needs_review` with a readiness score of `87/100`.

The most important finding is a duplicate geometry record. This may be valid for intersection datasets in some workflows, but it should be reviewed before using the data in spatial joins, network analysis, SQL Server loading, or downstream reporting.

- Status: `completed`
- Run ID: `demo-centreline-v011`

## Issue Counts

| Severity | Count | Meaning |
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

## Top Issues

- `[medium]` `DUPLICATE_GEOMETRY` feature `12`: Feature duplicates geometry of feature 11.
  Suggested fix: Deduplicate repeated spatial features.
- `[low]` `NULL_HEAVY_COLUMN`: Column 'ELEVATI12' is 98% null.
  Suggested fix: Review whether sparse fields should be populated or removed.
- `[low]` `NULL_HEAVY_COLUMN`: Column 'ELEVATI13' is 100% null.
  Suggested fix: Review whether sparse fields should be populated or removed.
- `[low]` `NULL_HEAVY_COLUMN`: Column 'HEIGHT_15' is 100% null.
  Suggested fix: Review whether sparse fields should be populated or removed.

## Business Value

- Converts geospatial QA from manual inspection into a repeatable run.
- Produces a readiness score that can be shared with data owners and downstream teams.
- Preserves feature-level IDs when available, making findings easier to trace back to source records.
- Writes machine-readable artifacts for audit, triage, and follow-up workflows.

## Artifacts

- output_dir: `demo/output`
- issues_csv: `demo/output/issues.csv`
- run_record: `demo/output/run_record.json`
- summary: `demo/output/summary.json`
- report: `demo/output/qa_report.md`
