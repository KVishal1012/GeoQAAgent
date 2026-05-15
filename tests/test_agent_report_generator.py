import json
from pathlib import Path

from geoqa.llm.gateway import StaticLLMGateway
from geoqa.reporting.agent_report_generator import generate_agent_report_artifacts
from geoqa.review.human_review import approve_agent_report
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

