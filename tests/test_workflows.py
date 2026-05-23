import json
from pathlib import Path

import pytest

from geoqa.llm.gateway import StaticLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.review.human_review import approve_agent_report, reject_agent_report
from geoqa.runner import run_geoqa
from geoqa.workflows import (
    HandoffBundleError,
    compare_run_outputs,
    export_handoff_bundle,
    generate_fix_plan_artifacts,
    load_comparison_index,
    load_run_index,
)


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def test_run_index_refreshes_review_status_after_transitions(tmp_path):
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
    rows = load_run_index(tmp_path / "outputs")
    assert rows[0]["review_status"] == "draft_ready"

    reject_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer", notes="Needs edits")
    rows = load_run_index(tmp_path / "outputs")
    assert rows[0]["review_status"] == "rejected"

    approve_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer", notes="Approved")
    rows = load_run_index(tmp_path / "outputs")
    assert rows[0]["review_status"] == "approved"


def test_run_index_reflects_blocked_status_from_failed_agent_report(tmp_path):
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
        gateway=StaticLLMGateway("The dataset contains 999 features and is safe for routing."),
    )

    rows = load_run_index(tmp_path / "outputs")
    assert rows[0]["review_status"] == "blocked"


def test_compare_run_outputs_persists_multiple_baselines(tmp_path):
    base_a = tmp_path / "base-a.geojson"
    base_b = tmp_path / "base-b.geojson"
    target_input = tmp_path / "target.geojson"
    _write_geojson(base_a, [{"type": "Feature", "properties": {"asset_id": "asset-a"}, "geometry": None}])
    _write_geojson(
        base_b,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-b"},
                "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
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

    base_result_a = run_geoqa(str(base_a), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    base_result_b = run_geoqa(str(base_b), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    target_result = run_geoqa(str(target_input), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])

    first = compare_run_outputs(base_result_a.artifact_paths["output_dir"], target_result.artifact_paths["output_dir"])
    second = compare_run_outputs(base_result_b.artifact_paths["output_dir"], target_result.artifact_paths["output_dir"])
    index = load_comparison_index(target_result.artifact_paths["output_dir"])

    assert first["comparison_key"] != second["comparison_key"]
    assert len(index) == 2
    assert Path(first["comparison_summary"]).exists()
    assert Path(second["comparison_summary"]).exists()


def test_fix_plan_generation_supports_custom_playbook_dir(tmp_path):
    input_path = tmp_path / "problem.geojson"
    playbook_dir = tmp_path / "playbooks"
    playbook_dir.mkdir()
    (playbook_dir / "geometry_fix_playbook.md").write_text("# Custom Geometry Fix\nUse custom remediation.", encoding="utf-8")
    _write_geojson(
        input_path,
        [{"type": "Feature", "properties": {"asset_id": None}, "geometry": None}],
    )
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])

    artifacts = generate_fix_plan_artifacts(result.artifact_paths["output_dir"], playbook_dir=playbook_dir)
    plan = json.loads(Path(artifacts["fix_plan_json"]).read_text(encoding="utf-8"))

    assert any(str(playbook_dir) in source for source in plan["playbook_sources"])


def test_handoff_bundle_blocks_when_required_artifacts_are_missing(tmp_path):
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

    with pytest.raises(HandoffBundleError):
        export_handoff_bundle(result.artifact_paths["output_dir"])


def test_handoff_bundle_exports_complete_bundle_with_selected_comparison(tmp_path):
    base_input = tmp_path / "base.geojson"
    target_input = tmp_path / "target.geojson"
    _write_geojson(base_input, [{"type": "Feature", "properties": {"asset_id": "asset-a"}, "geometry": None}])
    _write_geojson(
        target_input,
        [
            {
                "type": "Feature",
                "properties": {"asset_id": "asset-1"},
                "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
            }
        ],
    )
    base_result = run_geoqa(str(base_input), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    target_result = run_geoqa(str(target_input), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    generate_agent_report_artifacts(
        target_result,
        gateway=StaticLLMGateway(
            "GeoQA inspected target.geojson, containing 1 features with Point geometry in EPSG:4326. "
            "The dataset is classified as `ready` with a readiness score of 100/100. "
            "No QA findings were detected by the configured checks."
        ),
    )
    generate_fix_plan_artifacts(target_result.artifact_paths["output_dir"])
    comparison = compare_run_outputs(base_result.artifact_paths["output_dir"], target_result.artifact_paths["output_dir"])

    artifacts = export_handoff_bundle(
        target_result.artifact_paths["output_dir"],
        comparison_key=comparison["comparison_key"],
    )
    manifest = json.loads(Path(artifacts["bundle_manifest"]).read_text(encoding="utf-8"))

    assert manifest["complete"] is True
    assert manifest["selected_comparison_key"] == comparison["comparison_key"]
    assert any("comparisons/" in path for path in manifest["included_files"])
