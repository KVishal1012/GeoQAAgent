# GeoQA Agent-Assisted Report Draft

## Executive Summary

GeoQA inspected `centreline_intersections_sample.zip`, containing 50 features with MultiPoint geometry in EPSG:4326.

The dataset is classified as `needs_review` with a readiness score of `87/100`.

## Deterministic Findings

- Total findings: `4`
- Medium severity findings: `1`
- Low severity findings: `3`
- Most frequent finding type: `NULL_HEAVY_COLUMN` (`3` findings)

## Conditional Workflow Guidance

The `DUPLICATE_GEOMETRY` finding should be reviewed before downstream use.

## Evidence Boundary

This report is grounded in deterministic GeoQA artifacts and does not claim workflow suitability beyond those findings.
