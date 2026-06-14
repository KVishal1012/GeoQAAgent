# GeoQA Remediation Plan

Dataset: `centreline_intersections_sample.zip`

## `Duplicate Geometry`

- Priority: `Medium`
- Affected records: `1`
- Recommended action: Deduplicate repeated spatial features.
- Affected record IDs: `12`
- Example finding: Feature duplicates geometry of feature 11.
- Related guidance: `Duplicate Geometry Playbook`

## `Missing Required Column`

- Priority: `High`
- Affected records: `1`
- Recommended action: Add the required schema column.
- Affected data fields: `OBJECTID`
- Example finding: Required column 'OBJECTID' is missing.
- Related guidance: `Geometry And Schema Fix Playbook`

## `Null Heavy Column`

- Priority: `Low`
- Affected records: `3`
- Recommended action: Review whether sparse fields should be populated or removed.
- Affected data fields: `ELEVATI12`, `ELEVATI13`, `HEIGHT_15`
- Example finding: Column 'ELEVATI12' is 98% null.
- Related guidance: `Geometry And Schema Fix Playbook`
