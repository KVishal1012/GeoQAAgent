from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from typing import Any

from geoqa.config import AppConfig, ConfigError, diagnose_config, load_app_config
from geoqa.llm.gateway import StaticLLMGateway, build_openai_gateway
from geoqa.models import QAResult
from geoqa.reporting.agent_report_generator import (
    generate_agent_report_artifacts,
    read_agent_review_status,
    review_existing_agent_report,
)
from geoqa.runner import run_geoqa
from geoqa.workflows import compare_run_outputs, export_handoff_bundle, generate_fix_plan_artifacts, load_run_index


def run_uploaded_dataset(
    input_path: str,
    output_root: str,
    required_columns: list[str] | None = None,
    target_crs: str | None = None,
):
    return run_geoqa(
        input_path=input_path,
        output_root=output_root,
        required_columns=required_columns or [],
        target_crs=target_crs,
    )


def build_static_demo_report(result: QAResult, prompt_name: str = "technical_report_v1") -> str:
    dataset = result.summary.get("dataset", {})
    readiness = result.summary.get("readiness", {})
    issue_counts = result.issue_counts
    geometry_types = ", ".join(dataset.get("geometry_types", [])) or "unknown"

    if prompt_name == "executive_summary_v1":
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

    if prompt_name == "fix_recommendation_v1":
        lines = ["## Fix Recommendations", ""]
        if result.issues:
            for issue in result.issues:
                lines.append(f"- `{issue.issue_code}`: {issue.suggested_fix}")
        else:
            lines.append("- No fixes are recommended because the deterministic checks found no issues.")
        return "\n".join(lines)

    lines = [
        "# GeoQA Agent-Assisted Report Draft",
        "",
        "## Executive Summary",
        "",
        (
            f"GeoQA inspected `{dataset.get('filename', 'dataset')}`, containing "
            f"{dataset.get('feature_count', 0)} features with "
            f"{geometry_types} geometry in {dataset.get('crs', 'unknown CRS')}."
        ),
        "",
        (
            f"The dataset is classified as `{readiness.get('band', 'unknown')}` "
            f"with a readiness score of `{readiness.get('score', 0)}/100`."
        ),
        "",
        "## Evidence Used",
        "",
        (
            f"- `summary.json` reports {dataset.get('feature_count', 0)} features and "
            f"a readiness band of `{readiness.get('band', 'unknown')}`."
        ),
        (
            "- `run_record.json` captures the enabled checks, CRS, geometry type, "
            "and normalization notes for this run."
        ),
        (
            f"- `issues.csv` contains {issue_counts.get('total', 0)} findings."
        ),
        "",
        "## Key Findings",
        "",
    ]

    if result.issues:
        for issue in result.issues[:5]:
            lines.append(
                f"- `{issue.issue_code}` is reported as `{issue.severity}` severity: {issue.message}"
            )
    else:
        lines.append("- No QA findings were detected by the configured checks.")

    lines.extend(
        [
            "",
            "## Recommended Review Actions",
            "",
            "- Review the deterministic findings before downstream use.",
            "- Use the retrieved fix playbooks to confirm remediation steps before approving the AI report.",
            "",
            "## Limits of Interpretation",
            "",
            "- This draft is grounded in GeoQA evidence and retrieved playbook text.",
            "- It does not claim workflow suitability unless the deterministic QA evidence explicitly proves that result.",
        ]
    )
    return "\n".join(lines)


def generate_agent_draft(
    result: QAResult,
    model: str | None = None,
    playbook_dir: str | None = None,
    prompt_name: str = "technical_report_v1",
    use_static_demo: bool = False,
    runtime_config: dict[str, Any] | None = None,
    app_config: AppConfig | None = None,
):
    if app_config is not None and not app_config.agent_report_enabled:
        raise RuntimeError("Agent reports are disabled by GEOQA_AGENT_REPORT_ENABLED=0.")
    gateway = StaticLLMGateway(build_static_demo_report(result, prompt_name=prompt_name)) if use_static_demo else None
    if not use_static_demo and app_config is not None:
        gateway = build_openai_gateway(app_config, default_model=model or app_config.llm_model)
    return generate_agent_report_artifacts(
        result,
        gateway=gateway,
        model=model,
        playbook_dir=playbook_dir,
        prompt_name=prompt_name,
        approve=False,
        runtime_config=runtime_config,
    )


def review_agent_output(output_dir: str, action: str, reviewer_name: str, notes: str | None = None) -> dict[str, Any]:
    result = review_existing_agent_report(output_dir, action=action, reviewer_name=reviewer_name, notes=notes)
    result["review_status_payload"] = read_agent_review_status(output_dir)
    return result


def generate_fix_plan(output_dir: str) -> dict[str, str]:
    return generate_fix_plan_artifacts(output_dir)


def compare_existing_runs(base_output_dir: str, target_output_dir: str) -> dict[str, str]:
    return compare_run_outputs(base_output_dir, target_output_dir)


def export_handoff(output_dir: str) -> dict[str, str]:
    return export_handoff_bundle(output_dir)


def load_recent_runs(output_root: str) -> list[dict[str, Any]]:
    return load_run_index(output_root)


def load_run_artifacts(output_dir: str) -> dict[str, Any]:
    output_path = Path(output_dir)
    payload: dict[str, Any] = {"output_dir": str(output_path)}
    json_artifacts = {
        "summary": "summary.json",
        "run_record": "run_record.json",
        "report_consistency": "report_consistency.json",
        "hallucination_check": "hallucination_check.json",
        "review_status": "review_status.json",
        "agent_report_json": "agent_report.json",
        "fix_plan_json": "fix_plan.json",
        "comparison_summary": "comparison_summary.json",
        "bundle_manifest": "bundle_manifest.json",
    }
    text_artifacts = {
        "deterministic_report": "qa_report.md",
        "agent_report_draft": "agent_report_draft.md",
        "agent_report": "agent_report.md",
        "issues_csv": "issues.csv",
        "fix_plan_markdown": "fix_plan.md",
        "comparison_report": "comparison_report.md",
    }

    for key, filename in json_artifacts.items():
        path = output_path / filename
        payload[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    for key, filename in text_artifacts.items():
        path = output_path / filename
        payload[key] = path.read_text(encoding="utf-8") if path.exists() else None
        payload[f"{key}_path"] = str(path) if path.exists() else None
    payload["review_history"] = _read_json_lines(output_path / "review_history.jsonl")
    payload["issues_rows"] = _read_issues_csv_rows(output_path / "issues.csv")
    bundle_path = output_path / "handoff_bundle.zip"
    payload["handoff_bundle_path"] = str(bundle_path) if bundle_path.exists() else None
    return payload


def filter_issue_rows(
    issues: list[dict[str, Any]],
    *,
    severity: str | None = None,
    issue_code: str | None = None,
    feature_id: str | None = None,
    column_name: str | None = None,
) -> list[dict[str, Any]]:
    rows = issues
    if severity:
        rows = [row for row in rows if row.get("severity") == severity]
    if issue_code:
        rows = [row for row in rows if row.get("issue_code") == issue_code]
    if feature_id:
        rows = [row for row in rows if str(row.get("feature_id", "")) == feature_id]
    if column_name:
        rows = [
            row
            for row in rows
            if isinstance(row.get("context"), dict) and str(row["context"].get("column", "")) == column_name
        ]
    return rows


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_issues_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        context = row.get("context")
        row["context"] = json.loads(context) if context else {}
    return rows


def render_app() -> None:  # pragma: no cover - visual shell
    import streamlit as st

    st.set_page_config(page_title="GeoQA Agent", layout="wide")
    st.title("GeoQA Agent")
    st.caption("Deterministic spatial QA with evidence-backed agent report drafts and review controls.")

    try:
        config = load_app_config()
    except ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        return

    config_summary = diagnose_config(config)

    uploaded = st.file_uploader("Upload GeoJSON, GeoPackage, or zipped shapefile", type=["geojson", "json", "gpkg", "zip"])
    required_columns_text = st.text_input("Required columns", value="", help="Comma-separated column names.")
    target_crs = st.text_input("Target CRS", value="", help="Optional, for example EPSG:4326.")
    output_root = st.text_input("Output directory", value=config.output_root)
    existing_output_dir = st.text_input("Open existing run output directory", value="")

    st.subheader("Agent report options")
    include_agent_report = st.checkbox("Generate agent-assisted draft report")
    use_static_demo = st.checkbox("Use static demo mode (no API key)", value=not config.openai_api_key)
    llm_model = st.text_input("LLM model", value=config.llm_model or "")
    prompt_name = st.selectbox(
        "Prompt template",
        options=["technical_report_v1", "executive_summary_v1", "fix_recommendation_v1"],
        index=0,
    )
    reviewer_name = st.text_input("Reviewer name", value="")
    review_notes = st.text_area("Review notes", value="")

    if "latest_output_dir" not in st.session_state:
        st.session_state["latest_output_dir"] = None

    st.subheader("Recent runs")
    recent_runs = load_recent_runs(output_root)
    if recent_runs:
        labels = [
            f"{run['dataset_name']} | {run['readiness_band']} | {run['run_id']}"
            for run in recent_runs[:10]
        ]
        selected_recent_run = st.selectbox("Recent run browser", options=[""] + labels, index=0)
        if selected_recent_run:
            selected_entry = recent_runs[labels.index(selected_recent_run)]
            st.session_state["latest_output_dir"] = selected_entry["output_dir"]

    st.subheader("Runtime diagnostics")
    st.json(config_summary)
    if not config.agent_report_enabled:
        st.warning("Agent reports are disabled by configuration. Deterministic QA remains available.")
    elif not use_static_demo and (not config.openai_api_key or not (llm_model or config.llm_model)):
        st.warning("OpenAI mode is not ready. Provide OPENAI_API_KEY and a model, or use static demo mode.")

    if st.button("Open existing run", disabled=not existing_output_dir.strip()):
        st.session_state["latest_output_dir"] = existing_output_dir.strip()

    if st.button("Run GeoQA", type="primary", disabled=uploaded is None):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / uploaded.name
            input_path.write_bytes(uploaded.getvalue())
            required_columns = [column.strip() for column in required_columns_text.split(",") if column.strip()]
            result = run_uploaded_dataset(
                str(input_path),
                output_root=output_root,
                required_columns=required_columns,
                target_crs=target_crs or None,
            )
            st.session_state["latest_output_dir"] = result.artifact_paths["output_dir"]
            st.success(f"GeoQA completed: {result.run_record.readiness_band} ({result.run_record.readiness_score}/100)")

            if include_agent_report:
                try:
                    generate_agent_draft(
                        result,
                        model=llm_model or None,
                        prompt_name=prompt_name,
                        use_static_demo=use_static_demo,
                        runtime_config=config.to_safe_dict(),
                        app_config=config,
                    )
                except Exception as exc:  # pragma: no cover - streamlit operator surface
                    st.error(f"Agent draft generation failed: {exc}")

    output_dir = st.session_state.get("latest_output_dir")
    if output_dir:
        artifacts = load_run_artifacts(output_dir)
        st.subheader("Current run")
        st.code(output_dir)

        st.subheader("Deterministic artifacts")
        st.json(artifacts["summary"])
        if artifacts["deterministic_report"]:
            st.markdown(artifacts["deterministic_report"])
            st.download_button(
                "Download deterministic report",
                artifacts["deterministic_report"],
                file_name="qa_report.md",
            )
        if artifacts["issues_csv"]:
            st.download_button(
                "Download issues CSV",
                artifacts["issues_csv"],
                file_name="issues.csv",
            )

        st.subheader("Issue triage")
        triage_col1, triage_col2 = st.columns(2)
        with triage_col1:
            severity_filter = st.selectbox("Severity filter", options=["", "high", "medium", "low"], index=0)
            issue_code_options = [""] + sorted(
                {row.get("issue_code", "") for row in artifacts["issues_rows"] if row.get("issue_code")}
            )
            issue_code_filter = st.selectbox("Issue code filter", options=issue_code_options, index=0)
        with triage_col2:
            feature_id_filter = st.text_input("Feature ID filter", value="")
            column_options = [""] + sorted(
                {
                    str(row.get("context", {}).get("column"))
                    for row in artifacts["issues_rows"]
                    if isinstance(row.get("context"), dict) and row.get("context", {}).get("column")
                }
            )
            column_filter = st.selectbox("Column filter", options=column_options, index=0)
        filtered_rows = filter_issue_rows(
            artifacts["issues_rows"],
            severity=severity_filter or None,
            issue_code=issue_code_filter or None,
            feature_id=feature_id_filter or None,
            column_name=column_filter or None,
        )
        st.json(filtered_rows)

        if artifacts["review_status"]:
            st.subheader("Agent review status")
            st.json(artifacts["review_status"])
            status = artifacts["review_status"].get("status")
            if status == "blocked":
                st.error("Agent draft is blocked by consistency or grounding checks.")
            elif status == "draft_ready":
                st.info("Agent draft is ready for human review.")
            elif status == "rejected":
                st.warning("Agent draft has been rejected.")
            elif status == "approved":
                st.success("Agent report has been approved.")
        else:
            st.info("No agent review artifacts exist for this run yet.")

        if artifacts.get("agent_report_json"):
            st.subheader("Agent provenance")
            st.json(artifacts["agent_report_json"])

        if artifacts["agent_report_draft"]:
            st.subheader("Agent report draft")
            st.markdown(artifacts["agent_report_draft"])
            st.download_button(
                "Download agent draft",
                artifacts["agent_report_draft"],
                file_name="agent_report_draft.md",
            )

        if artifacts["report_consistency"] or artifacts["hallucination_check"]:
            left, right = st.columns(2)
            with left:
                st.subheader("Consistency check")
                st.json(artifacts["report_consistency"])
            with right:
                st.subheader("Hallucination monitor")
                st.json(artifacts["hallucination_check"])

        remediation_col1, remediation_col2 = st.columns(2)
        with remediation_col1:
            if st.button("Generate fix plan", disabled=not artifacts["issues_csv"]):
                generate_fix_plan(output_dir)
                st.rerun()
        with remediation_col2:
            if st.button("Export handoff bundle", disabled=not artifacts["summary"]):
                export_handoff(output_dir)
                st.rerun()

        if artifacts["fix_plan_markdown"]:
            st.subheader("Remediation plan")
            st.markdown(artifacts["fix_plan_markdown"])

        st.subheader("Compare runs")
        comparison_target = st.text_input("Compare current run against", value="")
        if st.button("Generate comparison", disabled=not comparison_target.strip()):
            compare_existing_runs(comparison_target.strip(), output_dir)
            st.rerun()
        if artifacts["comparison_report"]:
            st.markdown(artifacts["comparison_report"])

        review_col1, review_col2 = st.columns(2)
        with review_col1:
            if st.button("Approve draft", disabled=not reviewer_name or not artifacts["agent_report_draft"]):
                try:
                    review_agent_output(output_dir, action="approve", reviewer_name=reviewer_name, notes=review_notes or None)
                    st.rerun()
                except Exception as exc:  # pragma: no cover - streamlit operator surface
                    st.error(f"Approval failed: {exc}")
        with review_col2:
            if st.button("Reject draft", disabled=not reviewer_name or not artifacts["agent_report_draft"]):
                try:
                    review_agent_output(output_dir, action="reject", reviewer_name=reviewer_name, notes=review_notes or None)
                    st.rerun()
                except Exception as exc:  # pragma: no cover - streamlit operator surface
                    st.error(f"Rejection failed: {exc}")

        if artifacts["agent_report"]:
            st.subheader("Approved agent report")
            st.markdown(artifacts["agent_report"])
            st.download_button(
                "Download approved agent report",
                artifacts["agent_report"],
                file_name="agent_report.md",
            )

        if artifacts["review_history"]:
            st.subheader("Review history")
            st.json(artifacts["review_history"])

        if artifacts["handoff_bundle_path"]:
            bundle_path = Path(artifacts["handoff_bundle_path"])
            st.download_button(
                "Download handoff bundle",
                bundle_path.read_bytes(),
                file_name=bundle_path.name,
            )


if __name__ == "__main__":  # pragma: no cover - streamlit entrypoint
    render_app()
