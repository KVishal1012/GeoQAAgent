from __future__ import annotations

from typing import Any

from geoqa.models import QAResult

INTENDED_USE_LABELS = {
    "sql_load": "SQL/database loading",
    "dashboard": "dashboard or reporting",
    "migration": "GIS or asset-system migration",
    "routing": "routing or network analysis",
    "asset_handoff": "asset handoff",
    "spatial_join": "spatial joins or enrichment",
    "other": "general downstream use",
}


def build_customer_intake(
    *,
    customer_name: str | None = None,
    business_owner: str | None = None,
    dataset_name: str | None = None,
    intended_use: str | None = None,
    decision_context: str | None = None,
    required_columns: list[str] | None = None,
    target_crs: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    payload = {
        "customer_name": _clean(customer_name),
        "business_owner": _clean(business_owner),
        "dataset_name": _clean(dataset_name),
        "intended_use": _clean(intended_use),
        "intended_use_label": INTENDED_USE_LABELS.get(_clean(intended_use) or "", _clean(intended_use) or None),
        "decision_context": _clean(decision_context),
        "required_columns": [str(value).strip() for value in required_columns or [] if str(value).strip()],
        "target_crs": _clean(target_crs),
        "notes": _clean(notes),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def build_customer_report_context(qa_result: QAResult) -> dict[str, Any]:
    summary = qa_result.summary or {}
    dataset = summary.get("dataset", {})
    intake = summary.get("customer_intake", {}) or qa_result.run_record.customer_intake
    issue_counts = qa_result.issue_counts
    top_issues = sorted(
        qa_result.issues,
        key=lambda issue: {"high": 0, "medium": 1, "low": 2}.get(str(issue.severity), 3),
    )[:10]
    return {
        "customer_name": intake.get("customer_name", "Customer"),
        "business_owner": intake.get("business_owner"),
        "dataset_name": intake.get("dataset_name") or dataset.get("filename") or qa_result.run_record.filename,
        "intended_use": intake.get("intended_use"),
        "intended_use_label": intake.get("intended_use_label") or "downstream use",
        "decision_context": intake.get("decision_context"),
        "customer_notes": intake.get("notes"),
        "required_columns": intake.get("required_columns") or [],
        "target_crs": intake.get("target_crs") or qa_result.run_record.crs,
        "readiness_band": qa_result.run_record.readiness_band or summary.get("readiness", {}).get("band"),
        "readiness_score": qa_result.run_record.readiness_score or summary.get("readiness", {}).get("score"),
        "feature_count": dataset.get("feature_count", qa_result.run_record.feature_count),
        "geometry_profile": dataset.get("geometry_profile", {}),
        "spatial_anomalies": summary.get("spatial_anomalies", {}),
        "issue_counts": issue_counts,
        "top_issues": [issue.to_dict() for issue in top_issues],
        "workflow_guidance": build_workflow_guidance(qa_result, intake),
        "next_steps": build_recommended_next_steps(issue_counts, summary.get("spatial_anomalies", {})),
    }


def build_workflow_guidance(qa_result: QAResult, intake: dict[str, Any]) -> dict[str, str]:
    band = qa_result.run_record.readiness_band or qa_result.summary.get("readiness", {}).get("band")
    intended_use = str(intake.get("intended_use") or "other")
    issue_codes = {issue.issue_code for issue in qa_result.issues}
    issue_counts = qa_result.issue_counts
    high_count = int(issue_counts.get("high") or 0)
    label = INTENDED_USE_LABELS.get(intended_use, "downstream use")
    if band == "ready":
        decision = f"Ready for review before {label}."
        rationale = "GeoQA did not detect blocking findings under the configured checks."
    elif band == "not_ready" and high_count:
        decision = f"Needs review before {label} until high-severity findings are resolved."
        rationale = "GeoQA detected high-severity findings that should be fixed before production use."
    elif band == "not_ready":
        decision = (
            f"Needs review before {label}; cumulative medium- and low-severity findings reduced readiness "
            "below the configured threshold."
        )
        rationale = (
            "No high-severity findings were detected. Review the remaining findings and either remediate them "
            "or document their acceptance before production use."
        )
    else:
        decision = f"Needs review before {label}."
        if high_count:
            rationale = "GeoQA detected high-severity findings that should be resolved before downstream use."
        else:
            rationale = "GeoQA detected review-level findings that may be valid but should be confirmed before downstream use."

    if "SPATIAL_OUTLIER" in issue_codes:
        rationale += " Spatial outliers should be reviewed for CRS, coordinate order, source-record accuracy, or legitimate remote coverage."
    if "DUPLICATE_GEOMETRY" in issue_codes:
        rationale += " Duplicate geometries should be reviewed before joins, reporting, or network workflows."
    if "SQLSERVER_MISSING_SRID" in issue_codes or "SQLSERVER_INCOMPATIBLE_COLUMN_NAME" in issue_codes:
        rationale += " SQL Server compatibility findings should be addressed before database loading."
    return {"decision": decision, "rationale": rationale}


def build_recommended_next_steps(issue_counts: dict[str, int], spatial_anomalies: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if int(issue_counts.get("high") or 0):
        steps.append("Resolve high-priority findings before production loading or handoff.")
    elif int(issue_counts.get("medium") or 0):
        steps.append("Review medium-priority findings before production loading or handoff.")
    elif int(issue_counts.get("low") or 0):
        steps.append("Review low-priority findings and document any accepted data limitations.")
    else:
        steps.append("Confirm the dataset assumptions and intended-use requirements with the data owner.")
    if int(spatial_anomalies.get("count") or 0):
        steps.append("Confirm spatial anomalies with the source system of record.")
    steps.extend(
        [
            "Use `issues.csv` for record-level triage and assignment.",
            "Keep `summary.json`, `run_record.json`, and `geometry_profile.json` with the project audit trail.",
            "If findings are accepted as valid for the workflow, document the acceptance decision before downstream use.",
        ]
    )
    return steps


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def build_customer_comparison_context(comparison_summary: dict[str, Any], *, base_label: str | None = None, target_label: str | None = None) -> dict[str, Any]:
    severity_deltas = comparison_summary.get("issue_count_deltas_by_severity") or {}
    issue_code_deltas = comparison_summary.get("issue_count_deltas_by_issue_code") or {}
    new_issue_codes = comparison_summary.get("new_issue_codes") or []
    resolved_issue_codes = comparison_summary.get("resolved_issue_codes") or []
    readiness_delta = int(comparison_summary.get("readiness_score_delta") or 0)
    target_band = comparison_summary.get("readiness_band_target")
    if target_band == "ready":
        summary_line = "The dataset is now ready for downstream use based on the current GeoQA rules."
    elif target_band == "not_ready":
        summary_line = "The dataset still needs remediation before downstream use."
    else:
        summary_line = "The dataset still needs review before downstream use."
    return {
        "base_label": base_label or comparison_summary.get("base_run_id") or "baseline",
        "target_label": target_label or comparison_summary.get("target_run_id") or "current",
        "summary_line": summary_line,
        "readiness_score_delta": readiness_delta,
        "readiness_band_base": comparison_summary.get("readiness_band_base"),
        "readiness_band_target": target_band,
        "severity_deltas": severity_deltas,
        "issue_code_deltas": issue_code_deltas,
        "new_issue_codes": new_issue_codes,
        "resolved_issue_codes": resolved_issue_codes,
    }
