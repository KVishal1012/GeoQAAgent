# GeoQA Agent UAT Plan

These user acceptance tests verify the GeoQA pipeline from the perspective of a user running quality assurance on geospatial files.

## UAT-001: Clean GeoJSON Produces Ready Output

**Given** a valid GeoJSON file with distinct point features, an `asset_id` column, and EPSG:4326 coordinates

**When** the user runs GeoQA with `asset_id` as a required column

**Then** the run completes successfully, reports no issues, returns a readiness score of `100`, assigns the `ready` band, and writes all expected artifacts.

## UAT-002: Problem GeoJSON Produces Actionable Findings

**Given** a GeoJSON file with a missing required column, a null geometry, a zero-length line, and a sparse attribute column

**When** the user runs GeoQA with the missing column marked as required

**Then** the run completes successfully, returns a `not_ready` band, and reports issue codes for the expected quality failures.

## UAT-003: Zipped Shapefile Input Is Accepted

**Given** a complete shapefile packaged as a `.zip` with `.shp`, `.shx`, `.dbf`, and `.prj` components

**When** the user runs GeoQA on the zip file

**Then** the run completes successfully and writes the standard report, issue CSV, run record, and summary artifacts.

