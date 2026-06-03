# GeoQA Agent V1 Glossary

## Readiness Score

A 0-100 score that summarizes how much QA risk GeoQA found in a dataset. Higher is better.

## Readiness Band

A plain-English category derived from the readiness score. Examples include `ready`, `needs_review`, and `not_ready`.

## CRS

Coordinate Reference System. It tells software how to interpret coordinates on the earth.

## SRID

Spatial Reference Identifier. In databases such as SQL Server, this identifies the coordinate system used by spatial data.

## Geometry

The spatial shape of a feature, such as a point, line, polygon, MultiPoint, MultiLineString, or MultiPolygon.

## Duplicate Geometry

A finding where two records share the same spatial shape or location. This can be valid in some datasets, but it should be reviewed before joins, reporting, or network workflows.

## Null-Heavy Column

A field where many records have missing values. This may indicate optional metadata, incomplete data capture, or a field that should be removed before handoff.

## Agent Draft

An AI-generated report or recommendation that is grounded in GeoQA evidence. It is not final until review approval.

## Handoff Bundle

A package of QA artifacts intended for downstream teams. It can include reports, issue files, summaries, review status, fix plans, and validation results.

## Review Status

The current state of an AI-assisted output. V1 uses statuses such as `draft_ready`, `blocked`, `rejected`, and `approved`.
