from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


READINESS_BANDS = {"ready", "needs_review", "not_ready"}
SEVERITIES = {"high", "medium", "low"}
CHECK_MENTION_MAP = {
    "sql server": "sqlserver_checks",
    "linear reference": "linear_reference_checks",
    "linear referencing": "linear_reference_checks",
    "crs": "crs_checks",
    "srid": "sqlserver_checks",
    "schema": "schema_checks",
    "geometry": "geometry_checks",
    "polygon overlap": "geometry_checks",
}


@dataclass(slots=True)
class ReportConsistencyResult:
    passed: bool
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_claims: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_report_consistency(
    report_text: str,
    summary: dict[str, Any],
    issues: list[dict[str, Any]],
    run_record: dict[str, Any],
) -> ReportConsistencyResult:
    errors: list[str] = []
    warnings: list[str] = []
    checked_claims: list[dict[str, Any]] = []

    allowed_numbers = _extract_allowed_numbers(summary, issues, run_record)
    report_numbers = _extract_numbers(report_text)
    unsupported_numbers = sorted(report_numbers - allowed_numbers, key=_number_sort_key)
    for number in unsupported_numbers:
        errors.append(f"Unsupported numeric value in report: {number}")
    if report_numbers:
        checked_claims.append({"type": "numbers", "values": sorted(report_numbers, key=_number_sort_key)})

    expected_band = str(summary.get("readiness", {}).get("band", ""))
    report_bands = set(re.findall(r"`(ready|needs_review|not_ready)`", report_text))
    for band in sorted(report_bands - {expected_band}):
        errors.append(f"Readiness band '{band}' does not match summary band '{expected_band}'.")
    if report_bands:
        checked_claims.append({"type": "readiness_band", "values": sorted(report_bands)})

    known_issue_codes = {str(issue.get("issue_code")) for issue in issues if issue.get("issue_code")}
    report_issue_codes = set(re.findall(r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b", report_text))
    for issue_code in sorted(report_issue_codes - known_issue_codes):
        errors.append(f"Issue code '{issue_code}' is not present in issues.csv.")
    if report_issue_codes:
        checked_claims.append({"type": "issue_codes", "values": sorted(report_issue_codes)})

    severity_counts = _severity_counts(issues, run_record)
    for severity in sorted(SEVERITIES):
        if _mentions_positive_severity(report_text, severity) and severity_counts.get(severity, 0) == 0:
            errors.append(f"Report mentions {severity}-severity findings, but issues.csv has none.")
    checked_claims.append({"type": "severity_counts", "values": severity_counts})

    enabled_checks = set(run_record.get("enabled_checks", []))
    lowered_report = report_text.lower()
    for phrase, check_name in CHECK_MENTION_MAP.items():
        if phrase in lowered_report and check_name not in enabled_checks:
            errors.append(f"Report mentions '{phrase}' but {check_name} was not run.")
    checked_claims.append({"type": "enabled_checks", "values": sorted(enabled_checks)})

    if not issues and "finding" in lowered_report:
        warnings.append("Report mentions findings even though issues.csv is empty.")

    return ReportConsistencyResult(
        passed=not errors,
        blocking_errors=errors,
        warnings=warnings,
        checked_claims=checked_claims,
    )


def _extract_allowed_numbers(
    summary: dict[str, Any],
    issues: list[dict[str, Any]],
    run_record: dict[str, Any],
) -> set[str]:
    serialized = json.dumps(
        {"summary": summary, "issues": issues, "run_record": run_record},
        sort_keys=True,
        default=str,
    )
    numbers = _extract_numbers(serialized)
    if summary.get("readiness", {}).get("score") is not None:
        numbers.add("100")
    return numbers


def _extract_numbers(text: str) -> set[str]:
    pattern = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
    return {_normalize_number(match.group(0)) for match in pattern.finditer(text)}


def _normalize_number(value: str) -> str:
    normalized = value.replace(",", "").rstrip("%")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _number_sort_key(value: str) -> tuple[float, str]:
    try:
        return (float(value), value)
    except ValueError:
        return (0.0, value)


def _severity_counts(issues: list[dict[str, Any]], run_record: dict[str, Any]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    if run_record.get("issue_counts"):
        for severity in SEVERITIES:
            counts[severity] = int(run_record["issue_counts"].get(severity, 0))
        return counts
    for issue in issues:
        severity = str(issue.get("severity", ""))
        if severity in counts:
            counts[severity] += 1
    return counts


def _mentions_positive_severity(text: str, severity: str) -> bool:
    lowered = text.lower()
    for match in re.finditer(rf"\b{severity}[- ]severity\b|\b{severity}\b", lowered):
        prefix = lowered[max(0, match.start() - 12) : match.start()]
        if "no " in prefix or "zero " in prefix or "`0`" in prefix:
            continue
        return True
    return False

