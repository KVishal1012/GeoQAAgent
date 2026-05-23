import json
from pathlib import Path

from geoqa.llm.gateway import StaticLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.runner import run_geoqa
from geoqa.workflows import compare_run_outputs, export_handoff_bundle, generate_fix_plan_artifacts, load_run_index


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def test_run_index_appends_and_loads_recent_runs(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            }
        ],
    )

    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    rows = load_run_index(tmp_path / "outputs")

    assert rows
    assert rows[0]["run_id"] == result.run_record.run_id


def test_compare_run_outputs_detects_new_and_resolved_issue_codes(tmp_path):
    base_input = tmp_path / "base.geojson"
    target_input = tmp_path / "target.geojson"
    _write_geojson(
        base_input,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": None,
            }
        ],
    )
    _write_geojson(
        target_input,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-2"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            },
        ],
    )

    base_result = run_geoqa(str(base_input), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    target_result = run_geoqa(str(target_input), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    artifacts = compare_run_outputs(base_result.artifact_paths["output_dir"], target_result.artifact_paths["output_dir"])
    summary = json.loads(Path(artifacts["comparison_summary"]).read_text(encoding="utf-8"))

    assert "NULL_GEOMETRY" in summary["resolved_issue_codes"]
    assert "DUPLICATE_GEOMETRY" in summary["new_issue_codes"]


def test_fix_plan_generation_groups_issues_and_columns(tmp_path):
    input_path = tmp_path / "problem.geojson"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": None},
                "geometry": None,
            }
        ],
    )
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])

    artifacts = generate_fix_plan_artifacts(result.artifact_paths["output_dir"])
    plan = json.loads(Path(artifacts["fix_plan_json"]).read_text(encoding="utf-8"))

    assert any(group["issue_code"] == "NULL_HEAVY_COLUMN" for group in plan["issue_groups"])
    assert any(group["columns"] for group in plan["issue_groups"])


def test_handoff_bundle_contains_expected_manifest_entries(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(
        input_path,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            }
        ],
    )
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    generate_agent_report_artifacts(
        result,
        gateway=StaticLLMGateway(
            "GeoQA inspected clean.geojson, containing 1 features with Point geometry in EPSG:4326. "
            "The dataset is classified as `ready` with a readiness score of 100/100. "
            "No QA findings were detected by the configured checks."
        ),
    )
    generate_fix_plan_artifacts(result.artifact_paths["output_dir"])

    artifacts = export_handoff_bundle(result.artifact_paths["output_dir"])
    manifest = json.loads(Path(artifacts["bundle_manifest"]).read_text(encoding="utf-8"))

    assert "qa_report.md" in manifest["included_files"]
    assert "fix_plan.md" in manifest["included_files"]
