from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from geoqa.ops.pipeline_gate import PIPELINE_GATE_EXIT_CODE, evaluate_pipeline_gate
from geoqa.ops.watcher import scan_watch_folder_once


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def _clean_features() -> list[dict]:
    return [
        {
            "type": "Feature",
            "properties": {"asset_id": "asset-1", "name": "First"},
            "geometry": {"type": "Point", "coordinates": [-79.38, 43.65]},
        },
        {
            "type": "Feature",
            "properties": {"asset_id": "asset-2", "name": "Second"},
            "geometry": {"type": "Point", "coordinates": [-79.39, 43.66]},
        },
    ]


def _problem_features() -> list[dict]:
    return [
        {
            "type": "Feature",
            "properties": {"asset_id": "asset-1"},
            "geometry": {"type": "LineString", "coordinates": [[-79.38, 43.65], [-79.38, 43.65]]},
        },
        {
            "type": "Feature",
            "properties": {"asset_id": None},
            "geometry": None,
        },
    ]


def test_evaluate_pipeline_gate_blocks_below_threshold() -> None:
    result = evaluate_pipeline_gate(82, 85)

    assert result is not None
    assert result.passed is False
    assert result.exit_code == PIPELINE_GATE_EXIT_CODE
    assert "below" in result.message


def test_cli_fail_below_exits_two_after_writing_artifacts(tmp_path: Path) -> None:
    input_path = tmp_path / "problem.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(input_path, _problem_features())

    completed = subprocess.run(
        [
            sys.executable,
            "app.py",
            str(input_path),
            "--output-dir",
            str(output_root),
            "--required-column",
            "asset_id",
            "--required-column",
            "route_id",
            "--fail-below",
            "95",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == PIPELINE_GATE_EXIT_CODE
    payload = json.loads(completed.stdout)
    assert payload["pipeline_gate"]["passed"] is False
    assert payload["pipeline_gate"]["threshold"] == 95
    assert Path(payload["artifact_paths"]["summary"]).exists()
    assert "below the configured threshold" in completed.stderr


def test_cli_fail_below_passes_when_score_meets_threshold(tmp_path: Path) -> None:
    input_path = tmp_path / "clean.geojson"
    output_root = tmp_path / "outputs"
    _write_geojson(input_path, _clean_features())

    completed = subprocess.run(
        [
            sys.executable,
            "app.py",
            str(input_path),
            "--output-dir",
            str(output_root),
            "--required-column",
            "asset_id",
            "--fail-below",
            "95",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["pipeline_gate"]["passed"] is True
    assert payload["run_record"]["readiness_score"] == 100


def test_watch_folder_processes_new_drop_once_and_sends_slack_alert(monkeypatch, tmp_path: Path) -> None:
    watch_dir = tmp_path / "incoming"
    output_root = tmp_path / "outputs"
    state_file = tmp_path / "watch_state.json"
    watch_dir.mkdir()
    input_path = watch_dir / "problem.geojson"
    _write_geojson(input_path, _problem_features())
    alerts: list[dict] = []

    def fake_send_slack_alert(webhook_url: str, payload: dict) -> None:
        alerts.append({"webhook_url": webhook_url, "payload": payload})

    monkeypatch.setattr("geoqa.ops.watcher.send_slack_alert", fake_send_slack_alert)

    first = scan_watch_folder_once(
        watch_dir,
        output_root=output_root,
        state_file=state_file,
        fail_below=95,
        required_columns=["asset_id", "route_id"],
        slack_webhook_url="https://hooks.slack.test/geoqa",
    )
    second = scan_watch_folder_once(
        watch_dir,
        output_root=output_root,
        state_file=state_file,
        fail_below=95,
        required_columns=["asset_id", "route_id"],
        slack_webhook_url="https://hooks.slack.test/geoqa",
    )

    assert first["processed_count"] == 1
    assert first["processed"][0]["status"] == "completed"
    assert first["processed"][0]["pipeline_gate"]["passed"] is False
    assert first["processed"][0]["alert_sent"] is True
    assert alerts[0]["webhook_url"] == "https://hooks.slack.test/geoqa"
    assert "GeoQA gate blocked" in alerts[0]["payload"]["text"]
    assert state_file.exists()
    assert second["processed_count"] == 0
    assert second["skipped_count"] == 1
    assert second["skipped"][0]["reason"] == "already_processed"
