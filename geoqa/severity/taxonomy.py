from __future__ import annotations

from dataclasses import dataclass

from geoqa.models import Issue


@dataclass(frozen=True, slots=True)
class SeverityRule:
    severity: str
    suggested_fix: str


SEVERITY_MAP: dict[str, SeverityRule] = {
    "MISSING_CRS": SeverityRule("high", "Assign the correct CRS before using the dataset."),
    "OUT_OF_RANGE_COORDINATES": SeverityRule("high", "Verify CRS and coordinate units."),
    "NULL_GEOMETRY": SeverityRule("high", "Restore or remove features with null geometry."),
    "EMPTY_GEOMETRY": SeverityRule("high", "Restore or remove empty geometries."),
    "INVALID_GEOMETRY": SeverityRule("high", "Repair the invalid geometry before publishing."),
    "DUPLICATE_GEOMETRY": SeverityRule("medium", "Deduplicate repeated spatial features."),
    "MIXED_GEOMETRY_TYPES": SeverityRule("medium", "Split mixed geometry types into separate layers."),
    "OVERLAPPING_POLYGONS": SeverityRule("medium", "Resolve overlapping polygon boundaries."),
    "SUSPICIOUS_LARGE_FEATURE": SeverityRule("medium", "Confirm CRS and feature extent."),
    "SUSPICIOUS_SMALL_FEATURE": SeverityRule("low", "Review feature precision and snapping."),
    "ZERO_LENGTH_LINE": SeverityRule("medium", "Remove or repair zero-length line features."),
    "SPATIAL_OUTLIER": SeverityRule("medium", "Verify whether the remote feature location is valid, has the right CRS, and belongs in this dataset."),
    "MISSING_REQUIRED_COLUMN": SeverityRule("high", "Add the required schema column."),
    "NON_STRING_COLUMN_NAME": SeverityRule("medium", "Rename the column using a string identifier."),
    "LONG_COLUMN_NAME": SeverityRule("low", "Shorten the column name for downstream compatibility."),
    "NULL_HEAVY_COLUMN": SeverityRule("low", "Review whether sparse fields should be populated or removed."),
    "DUPLICATE_FEATURE_ID": SeverityRule("high", "Assign unique feature identifiers."),
    "SQLSERVER_INCOMPATIBLE_COLUMN_NAME": SeverityRule("low", "Rename the column to a SQL Server friendly identifier."),
    "SQLSERVER_MISSING_SRID": SeverityRule("medium", "Set the dataset CRS so SQL Server can use the right SRID."),
    "MISSING_LINEAR_MEASURE": SeverityRule("high", "Populate the missing route measures."),
    "REVERSED_LINEAR_MEASURE": SeverityRule("medium", "Correct measure direction so from_measure is not greater than to_measure."),
}


def apply_severity(issues: list[Issue]) -> list[Issue]:
    for issue in issues:
        rule = SEVERITY_MAP.get(
            issue.issue_code,
            SeverityRule("medium", "Review the issue and update the dataset accordingly."),
        )
        issue.severity = rule.severity
        issue.suggested_fix = issue.suggested_fix or rule.suggested_fix
    return issues
