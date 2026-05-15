# SQL Server Spatial Compatibility Playbook

Use this playbook when GeoQA reports SQL Server compatibility issues.

Grounded guidance:
- SQL Server spatial loading needs predictable column names and CRS/SRID metadata.
- Rename incompatible columns before loading into SQL Server tables.
- Confirm CRS and SRID before spatial indexing, spatial joins, or downstream reporting.
- If SQL Server checks were not enabled, do not claim SQL Server compatibility was validated.

