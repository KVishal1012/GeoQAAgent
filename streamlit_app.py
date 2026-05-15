from __future__ import annotations

import tempfile
from pathlib import Path

from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.runner import run_geoqa


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


def generate_agent_draft(result, model: str | None = None, playbook_dir: str | None = None):
    return generate_agent_report_artifacts(
        result,
        model=model,
        playbook_dir=playbook_dir,
        approve=False,
    )


def render_app() -> None:  # pragma: no cover - visual shell
    import streamlit as st

    st.set_page_config(page_title="GeoQA Agent", layout="wide")
    st.title("GeoQA Agent")
    st.caption("Deterministic spatial QA with evidence-backed agent report drafts.")

    uploaded = st.file_uploader("Upload GeoJSON, GeoPackage, or zipped shapefile", type=["geojson", "json", "gpkg", "zip"])
    required_columns_text = st.text_input("Required columns", value="", help="Comma-separated column names.")
    target_crs = st.text_input("Target CRS", value="", help="Optional, for example EPSG:4326.")
    output_root = st.text_input("Output directory", value="outputs")
    llm_model = st.text_input("LLM model", value="")
    include_agent_report = st.checkbox("Generate agent-assisted draft report")

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
            st.success(f"GeoQA completed: {result.run_record.readiness_band} ({result.run_record.readiness_score}/100)")
            st.json(result.summary)

            report_path = Path(result.artifact_paths["report"])
            st.subheader("Deterministic Report")
            st.markdown(report_path.read_text(encoding="utf-8"))

            if include_agent_report:
                agent_artifacts = generate_agent_draft(result, model=llm_model or None)
                st.subheader("Agent Draft Status")
                st.json(agent_artifacts)
                st.markdown(Path(agent_artifacts["agent_report_draft"]).read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover - streamlit entrypoint
    render_app()

