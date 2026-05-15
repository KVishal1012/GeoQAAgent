# CRS And SRID Playbook

Use this playbook for missing CRS, implausible coordinates, and SRID-related findings.

Grounded guidance:
- Assign the correct CRS before spatial analysis or database loading.
- For geographic CRS datasets, longitude should generally fall between -180 and 180 and latitude between -90 and 90.
- Confirm SRID mapping before loading spatial data into SQL Server.
- Do not infer the correct CRS from coordinates alone; treat CRS assignment as a data-owner decision.

