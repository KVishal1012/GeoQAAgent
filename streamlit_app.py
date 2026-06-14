from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import streamlit as st

from geoqa.config import AppConfig, diagnose_config, load_app_config
from geoqa.llm.gateway import StaticLLMGateway, build_openai_gateway
from geoqa.models import QAResult
from geoqa.reporting.agent_report_generator import (
    generate_agent_report_artifacts,
    read_agent_review_status,
    review_existing_agent_report,
)
from geoqa.review.human_review import read_review_history
from geoqa.runner import run_geoqa
from geoqa.workflows import (
    compare_run_outputs,
    export_handoff_bundle,
    generate_fix_plan_artifacts,
    load_comparison_index,
    load_run_index,
    load_selected_comparison,
)


DEFAULT_PAGE_SIZE = 25
AGENT_TASK_OPTIONS = ["report", "fix_plan", "handoff"]
TASK_PROMPT_OPTIONS = {
    "report": ["technical_report_v2", "executive_summary_v2", "technical_report_v1", "executive_summary_v1"],
    "fix_plan": ["fix_recommendation_v2", "fix_recommendation_v1"],
    "handoff": ["handoff_summary_v1", "technical_report_v2"],
}
PROMPT_ALIASES = {
    "technical_report_v1": "technical_report_v2",
    "executive_summary_v1": "executive_summary_v2",
    "fix_recommendation_v1": "fix_recommendation_v2",
}
DISPLAY_LABELS = {
    "run_id": "Run ID",
    "dataset_name": "Dataset",
    "started_at": "Started At",
    "finished_at": "Completed At",
    "readiness_band": "Readiness",
    "readiness_score": "Readiness Score",
    "review_status": "Review Status",
    "output_dir": "Output Folder",
    "comparison_key": "Comparison",
    "base_run_id": "Baseline Run",
    "target_run_id": "Compared Run",
    "severity": "Severity",
    "issue_code": "Finding Type",
    "message": "Finding Details",
    "feature_id": "Record ID",
    "suggested_fix": "Suggested Action",
    "context": "Evidence",
    "column": "Data Field",
    "report_path": "Report File",
    "summary_path": "Summary File",
    "generated_at": "Generated At",
    "name": "Tool",
    "reason": "Why It Was Used",
    "tool_count": "Tool Steps",
}


def run_uploaded_dataset(
    input_path: str,
    *,
    output_root: str,
    required_columns: list[str] | None = None,
    target_crs: str | None = None,
) -> QAResult:
    return run_geoqa(
        input_path=input_path,
        output_root=output_root,
        required_columns=required_columns or [],
        target_crs=target_crs,
    )


def build_static_demo_report(
    result: QAResult,
    prompt_name: str = "technical_report_v2",
    task: str = "report",
) -> str:
    dataset = result.summary.get("dataset", {})
    readiness = result.summary.get("readiness", {})
    issue_counts = result.issue_counts
    geometry_types = ", ".join(dataset.get("geometry_types", [])) or "unknown"
    prompt_name = PROMPT_ALIASES.get(prompt_name, prompt_name)

    if prompt_name == "executive_summary_v2":
        return "\n".join(
            [
                "## Executive Summary",
                "",
                (
                    f"GeoQA inspected `{dataset.get('filename', 'dataset')}`, containing "
                    f"{dataset.get('feature_count', 0)} features with {geometry_types} geometry in {dataset.get('crs', 'unknown CRS')}."
                ),
                "",
                (
                    f"The dataset is classified as `{readiness.get('band', 'unknown')}` "
                    f"with a readiness score of `{readiness.get('score', 0)}/100`."
                ),
                "",
                (
                    f"The deterministic issue set contains {issue_counts.get('total', 0)} findings. "
                    "Any downstream workflow guidance should be reviewed against the deterministic artifacts."
                ),
            ]
        )

    if prompt_name == "fix_recommendation_v2" or task == "fix_plan":
        lines = ["# GeoQA Remediation Plan Draft", "", "## Recommended Actions", ""]
        if result.issues:
            for issue in result.issues:
                lines.append(f"- `{_humanize_issue_code(issue.issue_code)}`: {issue.suggested_fix}")
        else:
            lines.append("- No fixes are recommended because the deterministic checks found no issues.")
        return "\n".join(lines)

    if prompt_name == "handoff_summary_v1" or task == "handoff":
        return "\n".join(
            [
                "# GeoQA Handoff Summary Draft",
                "",
                "## Analyst Summary",
                "",
                (
                    f"This handoff covers `{dataset.get('filename', 'dataset')}` with "
                    f"{dataset.get('feature_count', 0)} features and a readiness classification of `{readiness.get('band', 'unknown')}`."
                ),
                "",
                "## Included Evidence",
                "",
                "- Deterministic QA report",
                "- Issue spreadsheet",
                "- Run summary and run record",
                "- Review workflow artifacts",
                "- Remediation guidance when available",
            ]
        )

    lines = [
        "# GeoQA Agent-Assisted Report Draft",
        "",
        "## Executive Summary",
        "",
        (
            f"GeoQA inspected `{dataset.get('filename', 'dataset')}`, containing "
            f"{dataset.get('feature_count', 0)} features with {geometry_types} geometry in {dataset.get('crs', 'unknown CRS')}."
        ),
        "",
        (
            f"The dataset is classified as `{readiness.get('band', 'unknown')}` "
            f"with a readiness score of `{readiness.get('score', 0)}/100`."
        ),
        "",
        "## Deterministic Findings",
        "",
        f"- Total findings: `{issue_counts.get('total', 0)}`",
        f"- High severity findings: `{issue_counts.get('high', 0)}`",
        f"- Medium severity findings: `{issue_counts.get('medium', 0)}`",
        f"- Low severity findings: `{issue_counts.get('low', 0)}`",
        "",
        "## Conditional Workflow Guidance",
        "",
        "- Review the deterministic findings before downstream use.",
        "- Use the retrieved fix playbooks to confirm remediation steps before approving the AI report.",
        "",
        "## Limits of Interpretation",
        "",
        "- This draft is grounded in GeoQA evidence and retrieved playbook text.",
        "- It does not claim workflow suitability unless the deterministic QA evidence explicitly proves that result.",
    ]
    return "\n".join(lines)


def run_agent_session(
    result: QAResult,
    *,
    task: str = "report",
    model: str | None = None,
    playbook_dir: str | None = None,
    prompt_name: str | None = None,
    use_static_demo: bool = False,
    runtime_config: dict[str, Any] | None = None,
    app_config: AppConfig | None = None,
    max_steps: int | None = None,
    comparison_key: str | None = None,
) -> dict[str, str]:
    if app_config is not None and not app_config.agent_report_enabled:
        raise RuntimeError("Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.")

    selected_prompt = prompt_name or TASK_PROMPT_OPTIONS[task][0]
    normalized_prompt = PROMPT_ALIASES.get(selected_prompt, selected_prompt)
    if use_static_demo:
        gateway = StaticLLMGateway(build_static_demo_report(result, prompt_name=normalized_prompt, task=task))
    else:
        effective_config = app_config or load_app_config()
        gateway = build_openai_gateway(effective_config, default_model=model or effective_config.llm_model)

    return generate_agent_report_artifacts(
        result,
        gateway=gateway,
        model=model,
        playbook_dir=playbook_dir,
        prompt_name=normalized_prompt,
        task=task,
        max_steps=max_steps,
        comparison_key=comparison_key,
        runtime_config=runtime_config or (app_config.to_safe_dict() if app_config else {}),
    )


def generate_agent_draft(
    result: QAResult,
    model: str | None = None,
    playbook_dir: str | None = None,
    prompt_name: str = "technical_report_v1",
    use_static_demo: bool = False,
    runtime_config: dict[str, Any] | None = None,
    app_config: AppConfig | None = None,
):
    return run_agent_session(
        result,
        task="report",
        model=model,
        playbook_dir=playbook_dir,
        prompt_name=prompt_name,
        use_static_demo=use_static_demo,
        runtime_config=runtime_config,
        app_config=app_config,
    )


def review_agent_output(output_dir: str, action: str, reviewer_name: str, notes: str | None = None) -> dict[str, Any]:
    artifacts = review_existing_agent_report(output_dir, action=action, reviewer_name=reviewer_name, notes=notes)
    artifacts["review_status_payload"] = read_agent_review_status(output_dir)
    return artifacts


def generate_fix_plan(output_dir: str, playbook_dir: str | None = None) -> dict[str, str]:
    return generate_fix_plan_artifacts(output_dir, playbook_dir=playbook_dir)


def compare_existing_runs(base_output_dir: str, target_output_dir: str) -> dict[str, str]:
    return compare_run_outputs(base_output_dir, target_output_dir)


def export_handoff(output_dir: str, comparison_key: str | None = None) -> dict[str, str | bool]:
    return export_handoff_bundle(output_dir, comparison_key=comparison_key)


def load_recent_runs(output_root: str) -> list[dict[str, Any]]:
    return load_run_index(output_root)


def load_issue_filter_options(output_dir: str) -> dict[str, Any]:
    rows = _read_issues_csv(Path(output_dir) / "issues.csv")
    severity_counts: dict[str, int] = {}
    issue_code_counts: dict[str, int] = {}
    feature_ids: set[str] = set()
    columns: set[str] = set()

    for row in rows:
        severity = str(row.get("severity") or "")
        issue_code = str(row.get("issue_code") or "")
        feature_id = str(row.get("feature_id") or "")
        if severity:
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if issue_code:
            issue_code_counts[issue_code] = issue_code_counts.get(issue_code, 0) + 1
        if feature_id:
            feature_ids.add(feature_id)
        context = row.get("context")
        if isinstance(context, dict) and context.get("column"):
            columns.add(str(context["column"]))

    return {
        "total_rows": len(rows),
        "severity_counts": dict(sorted(severity_counts.items())),
        "issue_code_counts": dict(sorted(issue_code_counts.items())),
        "feature_ids": sorted(feature_ids),
        "columns": sorted(columns),
    }


def load_issue_rows_page(
    output_dir: str,
    *,
    severity: str | None = None,
    issue_code: str | None = None,
    feature_id: str | None = None,
    column: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    total_rows = 0
    page_rows: list[dict[str, Any]] = []
    for row in _iter_issue_rows(Path(output_dir) / "issues.csv"):
        if severity and row.get("severity") != severity:
            continue
        if issue_code and row.get("issue_code") != issue_code:
            continue
        if feature_id and str(row.get("feature_id") or "") != feature_id:
            continue
        if column:
            context = row.get("context")
            if not (isinstance(context, dict) and str(context.get("column") or "") == column):
                continue
        if total_rows >= offset and len(page_rows) < limit:
            page_rows.append(row)
        total_rows += 1
    return {
        "total_rows": total_rows,
        "offset": offset,
        "limit": limit,
        "rows": page_rows,
    }


def load_result_from_output_dir(output_dir: str) -> QAResult:
    from geoqa.models import Issue, RunRecord

    output_path = Path(output_dir)
    run_record_payload = _read_json_if_exists(output_path / "run_record.json") or {}
    summary_payload = _read_json_if_exists(output_path / "summary.json") or {}
    issue_payloads = _read_issues_csv(output_path / "issues.csv")
    issues = [Issue(**payload) for payload in issue_payloads]
    run_record = RunRecord(**run_record_payload)
    artifact_paths = {
        "output_dir": str(output_path),
        "report": str(output_path / "qa_report.md"),
        "issues_csv": str(output_path / "issues.csv"),
        "run_record": str(output_path / "run_record.json"),
        "summary": str(output_path / "summary.json"),
        "geometry_profile": str(output_path / "geometry_profile.json"),
    }
    return QAResult(run_record=run_record, issues=issues, summary=summary_payload, artifact_paths=artifact_paths)


def load_run_artifacts(output_dir: str, comparison_key: str | None = None) -> dict[str, Any]:
    output_path = Path(output_dir)
    payload: dict[str, Any] = {
        "output_dir": str(output_path),
        "summary": _read_json_if_exists(output_path / "summary.json"),
        "run_record": _read_json_if_exists(output_path / "run_record.json"),
        "geometry_profile": _read_json_if_exists(output_path / "geometry_profile.json"),
        "review_status": read_agent_review_status(output_path),
        "review_history": read_review_history(output_path),
        "qa_report": _read_text_if_exists(output_path / "qa_report.md"),
        "agent_report_draft": _read_text_if_exists(output_path / "agent_report_draft.md"),
        "agent_report": _read_text_if_exists(output_path / "agent_report.md"),
        "agent_report_json": _read_json_if_exists(output_path / "agent_report.json"),
        "agent_session": _read_json_if_exists(output_path / "agent_session.json"),
        "agent_trace": _read_json_if_exists(output_path / "agent_trace.json"),
        "report_consistency": _read_json_if_exists(output_path / "report_consistency.json"),
        "hallucination_check": _read_json_if_exists(output_path / "hallucination_check.json"),
        "fix_plan_markdown": _read_text_if_exists(output_path / "fix_plan.md"),
        "bundle_manifest": _read_json_if_exists(output_path / "bundle_manifest.json"),
        "comparison_index": load_comparison_index(output_path),
        "selected_comparison": load_selected_comparison(output_path, comparison_key=comparison_key),
    }
    payload["issue_filters"] = load_issue_filter_options(str(output_path))
    return payload


def render_app() -> None:  # pragma: no cover - visual shell
    st.set_page_config(page_title="GeoQA Agent", layout="wide")
    st.title("GeoQA Analyst Console")

    config = load_app_config()
    diagnostics = diagnose_config(config)
    output_root = config.output_root

    with st.sidebar:
        st.header("Runtime")
        st.code(output_root)
        if diagnostics["issues"]:
            st.warning("\n".join(diagnostics["issues"]))
        else:
            st.success("Runtime configuration looks healthy.")
        st.caption(f"Agent max steps: {config.agent_max_steps}")
        st.caption(f"Agent output token budget: {config.agent_output_token_budget}")

    st.subheader("Recent Runs")
    recent_runs = load_recent_runs(output_root)
    if recent_runs:
        st.dataframe(format_recent_runs_for_display(recent_runs), use_container_width=True)
        recent_options = [""] + [run.get("output_dir", "") for run in recent_runs if run.get("output_dir")]
        selected_recent = st.selectbox("Open a recent run", recent_options, format_func=lambda value: value or "Choose a recent run")
        if selected_recent:
            st.session_state["geoqa_output_dir"] = selected_recent
    else:
        st.info("No runs found yet.")

    st.subheader("Run Deterministic QA")
    input_path = st.text_input("Dataset path")
    required_columns = st.text_input("Required columns (comma separated)", value="asset_id")
    target_crs = st.text_input("Target CRS", value="")
    use_static_demo = st.checkbox("Static demo mode", value=not config.openai_api_key)
    run_agent_after_qa = st.checkbox("Run agent after QA", value=True)
    default_task = st.selectbox("Agent task", AGENT_TASK_OPTIONS, format_func=_humanize_status)
    prompt_name = st.selectbox(
        "Agent prompt",
        TASK_PROMPT_OPTIONS[default_task],
        index=0,
        format_func=_humanize_prompt_name,
    )
    if st.button("Run QA"):
        if not input_path.strip():
            st.error("Provide a dataset path first.")
        else:
            result = run_uploaded_dataset(
                input_path.strip(),
                output_root=output_root,
                required_columns=[value.strip() for value in required_columns.split(",") if value.strip()],
                target_crs=target_crs.strip() or None,
            )
            st.session_state["geoqa_output_dir"] = result.artifact_paths["output_dir"]
            st.success(f"Run complete: {result.artifact_paths['output_dir']}")
            if run_agent_after_qa:
                run_agent_session(
                    result,
                    task=default_task,
                    playbook_dir=None,
                    prompt_name=prompt_name,
                    use_static_demo=use_static_demo,
                    app_config=config,
                    runtime_config=config.to_safe_dict(),
                    max_steps=config.agent_max_steps,
                )
                st.success("Agent session completed.")

    st.subheader("Open Existing Run")
    existing_output_dir = st.text_input("Existing output directory", value=st.session_state.get("geoqa_output_dir", ""))
    if existing_output_dir.strip():
        st.session_state["geoqa_output_dir"] = existing_output_dir.strip()

    selected_output_dir = st.session_state.get("geoqa_output_dir")
    if not selected_output_dir:
        return

    artifacts = load_run_artifacts(selected_output_dir)
    st.subheader("Current Run")
    st.write(format_run_overview_for_display(selected_output_dir, artifacts))

    st.markdown("### Run Agent")
    agent_task = st.selectbox("Task", AGENT_TASK_OPTIONS, key="agent_task_selector", format_func=_humanize_status)
    agent_prompt = st.selectbox(
        "Prompt",
        TASK_PROMPT_OPTIONS[agent_task],
        key="agent_prompt_selector",
        format_func=_humanize_prompt_name,
    )
    playbook_dir = st.text_input("Custom playbook directory", value="")
    comparison_key = None
    if artifacts.get("comparison_index"):
        comparison_options = [""] + [item["comparison_key"] for item in artifacts["comparison_index"]]
        comparison_key = st.selectbox("Comparison for agent or handoff", comparison_options, format_func=lambda value: value if value else "None selected")
    agent_max_steps = st.number_input("Max tool steps", min_value=1, max_value=20, value=int(config.agent_max_steps), step=1)

    if st.button("Run Agent"):
        qa_result = load_result_from_output_dir(selected_output_dir)
        run_agent_session(
            qa_result,
            task=agent_task,
            playbook_dir=playbook_dir or None,
            prompt_name=agent_prompt,
            use_static_demo=use_static_demo,
            app_config=config,
            runtime_config=config.to_safe_dict(),
            max_steps=int(agent_max_steps),
            comparison_key=comparison_key or None,
        )
        st.success("Agent session completed.")
        artifacts = load_run_artifacts(selected_output_dir, comparison_key=comparison_key or None)

    session_payload = artifacts.get("agent_session") or {}
    trace_payload = artifacts.get("agent_trace") or {}
    review_payload = artifacts.get("review_status") or {}
    if session_payload:
        st.markdown("### Agent Session")
        st.write(format_agent_session_for_display(session_payload))
    if trace_payload:
        st.markdown("### Agent Trace")
        trace_rows = format_agent_trace_for_display(trace_payload)
        if trace_rows:
            st.dataframe(trace_rows, use_container_width=True)
    if artifacts.get("report_consistency") or artifacts.get("hallucination_check"):
        st.markdown("### Validation")
        st.write(format_validation_for_display(artifacts))
    if review_payload:
        st.markdown("### Review Status")
        st.write(format_review_status_for_display(review_payload))

    st.markdown("### Issue Triage")
    filters = artifacts["issue_filters"]
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        severity = st.selectbox("Severity", [""] + list(filters["severity_counts"].keys()), key="severity_filter", format_func=lambda value: _humanize_status(value) if value else "All")
    with col2:
        issue_code = st.selectbox("Finding type", [""] + list(filters["issue_code_counts"].keys()), key="issue_code_filter", format_func=lambda value: _humanize_issue_code(value) if value else "All")
    with col3:
        feature_id = st.selectbox("Record ID", [""] + filters["feature_ids"], key="feature_id_filter", format_func=lambda value: value if value else "All")
    with col4:
        column = st.selectbox("Data field", [""] + filters["columns"], key="column_filter", format_func=lambda value: value if value else "All")
    with col5:
        page_number = st.number_input("Page", min_value=1, value=1, step=1)

    page = load_issue_rows_page(
        selected_output_dir,
        severity=severity or None,
        issue_code=issue_code or None,
        feature_id=feature_id or None,
        column=column or None,
        limit=DEFAULT_PAGE_SIZE,
        offset=(int(page_number) - 1) * DEFAULT_PAGE_SIZE,
    )
    st.caption(f"Showing {len(page['rows'])} of {page['total_rows']} filtered rows")
    st.dataframe(format_issue_rows_for_display(page["rows"]), use_container_width=True)

    st.markdown("### Remediation")
    if st.button("Generate Fix Plan"):
        generate_fix_plan(selected_output_dir, playbook_dir=playbook_dir or None)
        st.success("Fix plan generated.")
        artifacts = load_run_artifacts(selected_output_dir)
    if artifacts.get("fix_plan_markdown"):
        st.markdown(artifacts["fix_plan_markdown"])

    st.markdown("### Compare Runs")
    comparison_target = st.text_input("Base run output directory")
    if st.button("Compare Against Base Run"):
        if comparison_target.strip():
            compare_existing_runs(comparison_target.strip(), selected_output_dir)
            st.success("Comparison generated.")
            artifacts = load_run_artifacts(selected_output_dir)
    if artifacts.get("comparison_index"):
        st.dataframe(format_comparisons_for_display(artifacts["comparison_index"]), use_container_width=True)

    st.markdown("### Review")
    reviewer_name = st.text_input("Reviewer name")
    review_notes = st.text_area("Review notes")
    review_cols = st.columns(2)
    with review_cols[0]:
        if st.button("Approve Draft"):
            review_agent_output(selected_output_dir, action="approve", reviewer_name=reviewer_name, notes=review_notes or None)
            st.success("Draft approved.")
            artifacts = load_run_artifacts(selected_output_dir)
    with review_cols[1]:
        if st.button("Reject Draft"):
            review_agent_output(selected_output_dir, action="reject", reviewer_name=reviewer_name, notes=review_notes or None)
            st.warning("Draft rejected.")
            artifacts = load_run_artifacts(selected_output_dir)

    st.markdown("### Handoff")
    handoff_comparison_key = None
    if artifacts.get("comparison_index"):
        handoff_options = [""] + [item["comparison_key"] for item in artifacts["comparison_index"]]
        handoff_comparison_key = st.selectbox("Comparison to include in bundle", handoff_options, format_func=lambda value: value if value else "Latest comparison")
    if st.button("Export Handoff Bundle"):
        bundle = export_handoff(selected_output_dir, comparison_key=handoff_comparison_key or None)
        st.success(f"Bundle created: {bundle['handoff_bundle']}")
        artifacts = load_run_artifacts(selected_output_dir, comparison_key=handoff_comparison_key or None)


def format_recent_runs_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for row in rows:
        issue_counts = row.get("issue_counts") or {}
        formatted.append(
            {
                "Run ID": row.get("run_id"),
                "Dataset": row.get("dataset_name"),
                "Completed At": row.get("finished_at") or row.get("started_at"),
                "Readiness": _humanize_status(row.get("readiness_band")),
                "Readiness Score": row.get("readiness_score"),
                "Review Status": _humanize_status(row.get("review_status")),
                "High Issues": issue_counts.get("high", 0),
                "Medium Issues": issue_counts.get("medium", 0),
                "Low Issues": issue_counts.get("low", 0),
                "Total Issues": issue_counts.get("total", 0),
                "Output Folder": row.get("output_dir"),
            }
        )
    return formatted


def format_run_overview_for_display(output_dir: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    summary = artifacts.get("summary") or {}
    dataset = summary.get("dataset") or {}
    readiness = summary.get("readiness") or {}
    geometry_profile = artifacts.get("geometry_profile") or dataset.get("geometry_profile") or {}
    spatial_anomalies = summary.get("spatial_anomalies") or {}
    session = artifacts.get("agent_session") or {}
    return {
        "Output Folder": output_dir,
        "Dataset": dataset.get("filename"),
        "Feature Count": dataset.get("feature_count"),
        "Geometry Type": ", ".join(dataset.get("geometry_types", [])) if dataset.get("geometry_types") else None,
        "Geometry Label": geometry_profile.get("primary_geometry_label"),
        "Spatial Anomalies": spatial_anomalies.get("count", 0),
        "Coordinate System": dataset.get("crs"),
        "Readiness": _humanize_status(readiness.get("band")),
        "Readiness Score": readiness.get("score"),
        "Review Status": _humanize_status((artifacts.get("review_status") or {}).get("status")),
        "Agent Task": _humanize_status(session.get("task")),
        "Agent Session Status": _humanize_status(session.get("status")),
        "Tool Steps": session.get("step_count"),
        "Total Findings": (artifacts.get("issue_filters") or {}).get("total_rows", 0),
    }


def format_issue_rows_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for row in rows:
        formatted.append(
            {
                "Severity": _humanize_status(row.get("severity")),
                "Finding Type": _humanize_issue_code(row.get("issue_code")),
                "Record ID": row.get("feature_id") or "",
                "Finding Details": row.get("message") or "",
                "Suggested Action": row.get("suggested_fix") or "",
                "Evidence": _format_context_for_display(row.get("context")),
            }
        )
    return formatted


def format_comparisons_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Comparison": row.get("comparison_key"),
            "Generated At": row.get("generated_at"),
            "Baseline Run": row.get("base_run_id"),
            "Compared Run": row.get("target_run_id"),
            "Summary File": row.get("summary_path"),
            "Report File": row.get("report_path"),
        }
        for row in rows
    ]


def format_agent_session_for_display(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "Task": _humanize_status(session.get("task")),
        "Status": _humanize_status(session.get("status")),
        "Provider": session.get("provider"),
        "Model": session.get("model"),
        "Prompt": _humanize_prompt_name(session.get("prompt_name")),
        "Planning Mode": _humanize_status(session.get("planning_mode")),
        "Tool Steps": session.get("step_count"),
        "Started At": session.get("started_at"),
        "Finished At": session.get("finished_at"),
    }


def format_agent_trace_for_display(trace: dict[str, Any]) -> list[dict[str, Any]]:
    calls = trace.get("tool_calls") or []
    rows: list[dict[str, Any]] = []
    for index, call in enumerate(calls, start=1):
        output_summary = call.get("output_summary") or {}
        rows.append(
            {
                "Step": index,
                "Tool": _humanize_tool_name(call.get("name")),
                "Why It Was Used": call.get("reason"),
                "Evidence Returned": _summarize_tool_output(output_summary),
            }
        )
    return rows


def format_validation_for_display(artifacts: dict[str, Any]) -> dict[str, Any]:
    consistency = artifacts.get("report_consistency") or {}
    hallucination = artifacts.get("hallucination_check") or {}
    return {
        "Consistency Check": "Passed" if consistency.get("passed") else "Blocked",
        "Consistency Issues": len(consistency.get("blocking_errors") or []),
        "Grounding Check": "Passed" if hallucination.get("passed") else "Blocked",
        "Grounding Issues": len(hallucination.get("blocking_errors") or []),
        "Warnings": len((consistency.get("warnings") or [])) + len((hallucination.get("warnings") or [])),
    }


def format_review_status_for_display(review_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "Status": _humanize_status(review_status.get("status")),
        "Reviewer": review_status.get("reviewer_name"),
        "Reviewed At": review_status.get("reviewed_at"),
        "Notes": review_status.get("notes"),
        "Blocking Issues": len(review_status.get("blocking_errors") or []),
        "Warnings": len(review_status.get("warnings") or []),
    }


def _humanize_issue_code(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _humanize_status(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _humanize_prompt_name(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _humanize_tool_name(value: Any) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _format_context_for_display(context: Any) -> str:
    if context in (None, "", {}):
        return ""
    if isinstance(context, dict):
        parts = []
        for key, value in context.items():
            label = DISPLAY_LABELS.get(str(key), str(key).replace("_", " ").title())
            parts.append(f"{label}: {value}")
        return "; ".join(parts)
    return str(context)


def _summarize_tool_output(output_summary: Any) -> str:
    if not isinstance(output_summary, dict):
        return str(output_summary)
    chunks: list[str] = []
    for key, value in output_summary.items():
        label = DISPLAY_LABELS.get(str(key), str(key).replace("_", " ").title())
        if isinstance(value, dict) and "count" in value:
            chunks.append(f"{label}: {value['count']} items")
        elif isinstance(value, dict):
            if "issue_count" in value:
                chunks.append(f"{label}: {value['issue_count']} issues")
            elif "total_rows" in value:
                chunks.append(f"{label}: {value['total_rows']} rows")
            elif "artifacts" in value:
                chunks.append(f"{label}: artifact bundle updated")
            else:
                chunks.append(f"{label}: available")
        else:
            chunks.append(f"{label}: {value}")
    return "; ".join(chunks)


def _read_issues_csv(path: Path) -> list[dict[str, Any]]:
    return list(_iter_issue_rows(path))


def _iter_issue_rows(path: Path):
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            context = row.get("context")
            if context:
                try:
                    row["context"] = json.loads(context)
                except json.JSONDecodeError:
                    row["context"] = context
            yield row


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - visual shell
    render_app()
