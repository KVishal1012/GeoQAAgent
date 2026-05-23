import json
from pathlib import Path

import pytest

from app import build_parser, validate_args
from geoqa.llm.gateway import LLMGatewayError, OpenAILLMGateway, StaticFileLLMGateway, StaticLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts, review_existing_agent_report
from geoqa.review.human_review import ReviewError, approve_agent_report, read_review_history, read_review_status, reject_agent_report
from geoqa.runner import run_geoqa


def _write_clean_geojson(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-1"},
                        "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"asset_id": "asset-2"},
                        "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_agent_report_generation_writes_draft_but_not_final_before_approval(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100. "
        "No QA findings were detected by the configured checks."
    )

    artifacts = generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))
    output_dir = Path(result.artifact_paths["output_dir"])

    assert Path(artifacts["agent_report_draft"]).exists()
    assert Path(artifacts["report_consistency"]).exists()
    assert Path(artifacts["hallucination_check"]).exists()
    assert Path(artifacts["review_status"]).exists()
    assert Path(artifacts["review_history"]).exists()
    assert not (output_dir / "agent_report.md").exists()


def test_agent_report_approval_writes_final_report(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )
    generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))

    status = approve_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer")

    assert status.status == "approved"
    assert Path(status.final_path).exists()


def test_agent_report_approval_requires_reviewer_name(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )
    generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))

    with pytest.raises(ReviewError):
        approve_agent_report(result.artifact_paths["output_dir"], reviewer_name="")


def test_agent_report_rejection_persists_review_state(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )
    generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))

    status = reject_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer", notes="Needs rewrite")

    assert status.status == "rejected"
    assert status.notes == "Needs rewrite"
    stored = read_review_status(result.artifact_paths["output_dir"])
    assert stored is not None
    assert stored.status == "rejected"


def test_review_history_appends_events_in_order(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )
    generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))
    reject_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer", notes="Needs edits")
    approve_agent_report(result.artifact_paths["output_dir"], reviewer_name="QA Reviewer", notes="Approved after review")

    history = read_review_history(result.artifact_paths["output_dir"])

    assert [entry["action"] for entry in history] == ["draft_ready", "rejected", "approved"]


def test_failed_consistency_check_blocks_final_report(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    invalid_report = "The dataset contains 999 features and is classified as `not_ready`."

    with pytest.raises(ReviewError):
        generate_agent_report_artifacts(
            result,
            gateway=StaticLLMGateway(invalid_report),
            approve=True,
            reviewer_name="QA Reviewer",
        )

    output_dir = Path(result.artifact_paths["output_dir"])
    assert (output_dir / "agent_report_draft.md").exists()
    assert not (output_dir / "agent_report.md").exists()
    status = read_review_status(output_dir)
    assert status is not None
    assert status.status == "blocked"


def test_static_file_gateway_works_without_api_key(tmp_path):
    report_path = tmp_path / "static-report.md"
    report_path.write_text("Static grounded report.", encoding="utf-8")

    response = StaticFileLLMGateway(str(report_path)).generate("ignored")

    assert response.provider == "static"
    assert response.text == "Static grounded report."


def test_static_file_gateway_generates_agent_artifacts_without_api_key(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_path = tmp_path / "static-report.md"
    report_path.write_text(
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100. "
        "No QA findings were detected by the configured checks.",
        encoding="utf-8",
    )

    artifacts = generate_agent_report_artifacts(result, gateway=StaticFileLLMGateway(str(report_path)))

    assert Path(artifacts["agent_report_draft"]).exists()
    assert Path(artifacts["report_consistency"]).exists()
    assert Path(artifacts["hallucination_check"]).exists()


def test_openai_gateway_fails_gracefully_without_api_key():
    gateway = OpenAILLMGateway(api_key=None, default_model="gpt-test-model")

    with pytest.raises(LLMGatewayError, match="OPENAI_API_KEY"):
        gateway.generate("prompt")


def test_prompt_selection_is_recorded_in_agent_json(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )

    artifacts = generate_agent_report_artifacts(
        result,
        gateway=StaticLLMGateway(report_text),
        prompt_name="executive_summary_v1",
    )

    payload = json.loads(Path(artifacts["agent_report_json"]).read_text(encoding="utf-8"))
    assert payload["prompt_name"] == "executive_summary_v1"
    assert payload["review_status"]["status"] == "draft_ready"
    assert "generated_at" in payload


def test_existing_draft_can_be_approved_without_regeneration(tmp_path):
    input_path = tmp_path / "clean.geojson"
    _write_clean_geojson(input_path)
    result = run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])
    report_text = (
        "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
        "The dataset is classified as `ready` with a readiness score of 100/100."
    )
    artifacts = generate_agent_report_artifacts(result, gateway=StaticLLMGateway(report_text))

    review_result = review_existing_agent_report(
        result.artifact_paths["output_dir"],
        action="approve",
        reviewer_name="QA Reviewer",
        notes="Approved after review",
    )

    assert Path(review_result["review_status"]).exists()
    assert Path(review_result["agent_report"]).exists()
    assert Path(review_result["review_history"]).exists()
    payload = json.loads(Path(artifacts["agent_report_json"]).read_text(encoding="utf-8"))
    assert payload["review_status"]["status"] == "approved"


def test_cli_requires_reviewer_name_for_approval():
    parser = build_parser()
    args = parser.parse_args(["demo/input/centreline_intersections_sample.zip", "--agent-report", "--approve-agent-report"])

    with pytest.raises(SystemExit):
        validate_args(args, parser)


def test_cli_allows_existing_review_without_input_path():
    parser = build_parser()
    args = parser.parse_args(["--review-output-dir", "outputs/run-123", "--approve-agent-report", "--reviewer-name", "QA Reviewer"])

    validate_args(args, parser)


def test_cli_allows_diagnose_config_without_input_path():
    parser = build_parser()
    args = parser.parse_args(["--diagnose-config"])

    validate_args(args, parser)
