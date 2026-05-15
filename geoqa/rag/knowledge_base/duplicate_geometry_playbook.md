# Duplicate Geometry Playbook

Use this playbook when GeoQA reports duplicate geometry records.

Grounded guidance:
- Duplicate geometries can indicate duplicate records, conflated assets, or valid multi-record modeling.
- For intersection datasets, duplicate point geometries may be valid when multiple records describe the same physical location at different levels or classifications.
- Review duplicate geometry findings before spatial joins, network analysis, SQL Server loading, or downstream reporting.
- Do not state that duplicate geometries make a dataset unusable unless the workflow requirements prove that conclusion.

