# Geometry And Schema Fix Playbook

Use this playbook for geometry validity, null geometry, mixed geometry, size anomaly, schema, and sparse column findings.

Grounded guidance:
- Null or empty geometries should be restored from source data or removed before publishing.
- Invalid geometries should be repaired with a GIS repair workflow and rechecked.
- Mixed geometry types should be split into separate layers when downstream systems expect one geometry family.
- Null-heavy columns should be reviewed with the data owner before removal or population.
- Required schema fields should be added or mapped before downstream use.

