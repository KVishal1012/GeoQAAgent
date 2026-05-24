import json
from pathlib import Path

from geoqa.agent.runtime import run_agent_task_artifacts
from geoqa.llm.gateway import LLMResponse
from geoqa.runner import run_geoqa


class SequencedGateway:
    provider = "static-sequenced"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt: str, model: str | None = None) -> LLMResponse:
        self.prompts.append(prompt)
        payload = self.responses.pop(0)
        return LLMResponse(
            text=payload,
            model=model or "static-sequenced-model",
            provider=self.provider,
            raw={"remaining": len(self.responses)},
        )


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _clean_result(tmp_path: Path):
    input_path = tmp_path / "clean.geojson"
    _write_geojson(
        input_path,
        [
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
    )
    return run_geoqa(str(input_path), output_root=str(tmp_path / "outputs"), required_columns=["asset_id"])


def test_agent_runtime_records_planned_tool_sequence_for_report(tmp_path):
    result = _clean_result(tmp_path)
    gateway = SequencedGateway(
        [
            json.dumps(
                {
                    "steps": [
                        {"tool": "load_run_evidence", "reason": "Load run evidence."},
                        {"tool": "load_issue_summary", "reason": "Summarize findings."},
                        {"tool": "load_issue_rows_page", "reason": "Inspect example rows."},
                    ]
                }
            ),
            (
                "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
                "The dataset is classified as `ready` with a readiness score of `100/100`."
            ),
        ]
    )

    artifacts = run_agent_task_artifacts(result, gateway=gateway, task="report", max_steps=3)
    trace = json.loads(Path(artifacts["agent_trace"]).read_text(encoding="utf-8"))
    session = json.loads(Path(artifacts["agent_session"]).read_text(encoding="utf-8"))

    assert [call["name"] for call in trace["tool_calls"]] == [
        "load_run_evidence",
        "load_issue_summary",
        "load_issue_rows_page",
    ]
    assert session["planning_mode"] == "llm"
    assert session["step_count"] == 3


def test_agent_runtime_respects_max_steps(tmp_path):
    result = _clean_result(tmp_path)
    gateway = SequencedGateway(
        [
            json.dumps(
                {
                    "steps": [
                        {"tool": "load_run_evidence", "reason": "Load run evidence."},
                        {"tool": "load_issue_summary", "reason": "Summarize findings."},
                        {"tool": "load_issue_rows_page", "reason": "Inspect rows."},
                    ]
                }
            ),
            (
                "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
                "The dataset is classified as `ready` with a readiness score of `100/100`."
            ),
        ]
    )

    artifacts = run_agent_task_artifacts(result, gateway=gateway, task="report", max_steps=1)
    trace = json.loads(Path(artifacts["agent_trace"]).read_text(encoding="utf-8"))
    session = json.loads(Path(artifacts["agent_session"]).read_text(encoding="utf-8"))

    assert len(trace["tool_calls"]) == 1
    assert trace["tool_calls"][0]["name"] == "load_run_evidence"
    assert session["step_count"] == 1


def test_agent_runtime_fix_plan_task_writes_fix_plan_artifacts(tmp_path):
    result = _clean_result(tmp_path)
    gateway = SequencedGateway(
        [
            json.dumps(
                {
                    "steps": [
                        {"tool": "load_run_evidence", "reason": "Load run evidence."},
                        {"tool": "generate_fix_plan", "reason": "Create a remediation plan."},
                    ]
                }
            ),
            "# GeoQA Remediation Plan Draft\n\nNo fixes are recommended because the deterministic checks found no issues.",
        ]
    )

    artifacts = run_agent_task_artifacts(result, gateway=gateway, task="fix_plan", max_steps=2)
    trace = json.loads(Path(artifacts["agent_trace"]).read_text(encoding="utf-8"))
    session = json.loads(Path(artifacts["agent_session"]).read_text(encoding="utf-8"))

    assert any(call["name"] == "generate_fix_plan" for call in trace["tool_calls"])
    assert Path(result.artifact_paths["output_dir"], "fix_plan.md").exists()
    assert session["task"] == "fix_plan"


def test_agent_runtime_blocks_unsupported_tool_supported_claim(tmp_path):
    result = _clean_result(tmp_path)
    gateway = SequencedGateway(
        [
            json.dumps(
                {
                    "steps": [
                        {"tool": "load_run_evidence", "reason": "Load run evidence."},
                        {"tool": "load_issue_summary", "reason": "Summarize findings."},
                    ]
                }
            ),
            (
                "GeoQA inspected clean.geojson, containing 2 features with Point geometry in EPSG:4326. "
                "The dataset is classified as `ready` with a readiness score of `100/100`. "
                "This handoff bundle is ready for downstream teams."
            ),
        ]
    )

    artifacts = run_agent_task_artifacts(result, gateway=gateway, task="report", max_steps=2)
    review_status = json.loads(Path(artifacts["review_status"]).read_text(encoding="utf-8"))
    consistency = json.loads(Path(artifacts["report_consistency"]).read_text(encoding="utf-8"))

    assert review_status["status"] == "blocked"
    assert consistency["passed"] is False
    assert any("handoff bundle" in item.lower() for item in consistency["blocking_errors"])
