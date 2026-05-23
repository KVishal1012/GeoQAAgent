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
    report_issue_codes = _extract_report_issue_codes(report_text)
    for issue_code in sorted(report_issue_codes - known_issue_codes):
        errors.append(f"Issue code '{issue_code}' is not present in issues.csv.")
    if report_issue_codes:
        checked_claims.append({"type": "issue_codes", "values": sorted(report_issue_codes)})

    severity_counts = _severity_counts(issues, run_record)
    issue_code_counts = _issue_code_counts(issues)
    for severity in sorted(SEVERITIES):
        if _mentions_positive_severity(report_text, severity) and severity_counts.get(severity, 0) == 0:
            errors.append(f"Report mentions {severity}-severity findings, but issues.csv has none.")
    _validate_explicit_severity_counts(report_text, severity_counts, errors)
    _validate_no_severity_claims(report_text, severity_counts, errors)
    _validate_explicit_issue_code_counts(report_text, issue_code_counts, errors)
    _validate_no_findings_claim(report_text, issues, errors)
    checked_claims.append({"type": "severity_counts", "values": severity_counts})
    checked_claims.append({"type": "issue_code_counts", "values": issue_code_counts})

    feature_ids = {str(issue.get("feature_id")) for issue in issues if issue.get("feature_id") not in (None, "")}
    referenced_feature_ids = _extract_referenced_feature_ids(report_text)
    for feature_id in sorted(referenced_feature_ids - feature_ids):
        errors.append(f"Feature ID '{feature_id}' is not present in issues.csv.")
    if referenced_feature_ids:
        checked_claims.append({"type": "feature_ids", "values": sorted(referenced_feature_ids)})

    columns = {str(column) for column in summary.get("dataset", {}).get("columns", []) if column}
    issue_context_columns = {
        str(issue.get("context", {}).get("column"))
        for issue in issues
        if isinstance(issue.get("context"), dict) and issue.get("context", {}).get("column")
    }
    known_columns = columns | issue_context_columns
    referenced_columns = _extract_referenced_columns(report_text, known_issue_codes)
    for column in sorted(referenced_columns - known_columns):
        errors.append(f"Column '{column}' is not present in summary.json or issues.csv.")
    if referenced_columns:
        checked_claims.append({"type": "columns", "values": sorted(referenced_columns)})

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


def _issue_code_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        issue_code = str(issue.get("issue_code", ""))
        if not issue_code:
            continue
        counts[issue_code] = counts.get(issue_code, 0) + 1
    return counts


def _mentions_positive_severity(text: str, severity: str) -> bool:
    lowered = text.lower()
    for match in re.finditer(rf"\b{severity}[- ]severity\b|\b{severity}\b", lowered):
        prefix = lowered[max(0, match.start() - 12) : match.start()]
        if "no " in prefix or "zero " in prefix or "`0`" in prefix:
            continue
        return True
    return False


def _extract_report_issue_codes(report_text: str) -> set[str]:
    candidates: set[str] = set()
    for match in re.finditer(r"`([A-Z][A-Z0-9]+_[A-Z0-9_]+)`", report_text):
        token = match.group(1)
        suffix = token.split("_", 1)[1]
        if any(character.isalpha() for character in suffix):
            candidates.add(token)
    return candidates


def _validate_explicit_severity_counts(text: str, severity_counts: dict[str, int], errors: list[str]) -> None:
    for match in re.finditer(r"\b(\d+)\s+(high|medium|low)(?:-|\s+)severity\b", text.lower()):
        stated_count = int(match.group(1))
        severity = match.group(2)
        actual_count = severity_counts.get(severity, 0)
        if stated_count != actual_count:
            errors.append(
                f"Report says there are {stated_count} {severity}-severity findings, but issues.csv has {actual_count}."
            )


def _validate_no_severity_claims(text: str, severity_counts: dict[str, int], errors: list[str]) -> None:
    lowered = text.lower()
    for severity in SEVERITIES:
        if re.search(rf"\bno\s+{severity}(?:-|\s+)severity\s+(?:issues|findings)\b", lowered):
            actual_count = severity_counts.get(severity, 0)
            if actual_count != 0:
                errors.append(
                    f"Report says there are no {severity}-severity findings, but issues.csv has {actual_count}."
                )


def _validate_explicit_issue_code_counts(text: str, issue_code_counts: dict[str, int], errors: list[str]) -> None:
    for match in re.finditer(r"\b(\d+)\s+`([A-Z][A-Z0-9]+_[A-Z0-9_]+)`\s+findings?\b", text):
        stated_count = int(match.group(1))
        issue_code = match.group(2)
        actual_count = issue_code_counts.get(issue_code, 0)
        if stated_count != actual_count:
            errors.append(
                f"Report says there are {stated_count} {issue_code} findings, but issues.csv has {actual_count}."
            )


def _validate_no_findings_claim(text: str, issues: list[dict[str, Any]], errors: list[str]) -> None:
    lowered = text.lower()
    if (
        "no qa findings" in lowered
        or "no findings were detected" in lowered
        or "no issues were detected" in lowered
    ) and issues:
        errors.append("Report says there are no findings, but issues.csv is not empty.")


def _extract_referenced_feature_ids(text: str) -> set[str]:
    feature_ids: set[str] = set()
    for match in re.finditer(r"\bfeature\s+`([^`]+)`", text, flags=re.IGNORECASE):
        feature_ids.add(match.group(1))
    return feature_ids


def _extract_referenced_columns(text: str, known_issue_codes: set[str]) -> set[str]:
    columns: set[str] = set()
    reserved_tokens = known_issue_codes | READINESS_BANDS | SEVERITIES
    for token in re.findall(r"`([^`]+)`", text):
        if token in reserved_tokens:
            continue
        if token.startswith("EPSG:"):
            continue
        if token.endswith(".zip") or token.endswith(".geojson") or token.endswith(".gpkg"):
            continue
        if re.fullmatch(r"feature-\d+", token) or token.isdigit():
            continue
        if token in {"Point", "MultiPoint", "LineString", "Polygon", "MultiPolygon", "MultiLineString"}:
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            columns.add(token)
    return columns
