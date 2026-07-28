from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geoqa.runner import run_geoqa


@dataclass(slots=True)
class PilotDatasetResult:
    name: str
    input_path: str
    run_id: str | None
    status: str
    readiness_score: int | None
    readiness_band: str | None
    issue_count: int | None
    output_dir: str | None
    acceptance_passed: bool
    error: str | None = None


def run_three_dataset_pilot(manifest_path: str | Path, output_root: str | Path) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    datasets = manifest.get("datasets") or []
    if len(datasets) != 3:
        raise ValueError("The V1.2 pilot manifest must contain exactly three datasets.")

    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)
    results: list[PilotDatasetResult] = []
    for entry in datasets:
        name = str(entry.get("name") or "").strip()
        raw_input = Path(str(entry.get("input_path") or ""))
        input_path = raw_input if raw_input.is_absolute() else (manifest_file.parent / raw_input).resolve()
        try:
            qa_result = run_geoqa(
                str(input_path),
                output_root=str(output_path),
                required_columns=list(entry.get("required_columns") or []),
                target_crs=entry.get("target_crs"),
                customer_intake={
                    "customer_name": entry.get("customer_name") or "V1.2 pilot customer",
                    "dataset_name": name,
                    "intended_use": entry.get("intended_use") or "other",
                    "decision_context": entry.get("decision_context") or "V1.2 real-world pilot acceptance",
                    "notes": entry.get("notes") or "",
                },
            )
            score = qa_result.run_record.readiness_score
            minimum_score = int(entry.get("minimum_score", 0))
            allowed_bands = list(entry.get("allowed_bands") or ["ready", "needs_review", "not_ready"])
            accepted = (
                qa_result.run_record.status == "completed"
                and score is not None
                and score >= minimum_score
                and qa_result.run_record.readiness_band in allowed_bands
            )
            results.append(
                PilotDatasetResult(
                    name=name,
                    input_path=str(input_path),
                    run_id=qa_result.run_record.run_id,
                    status=qa_result.run_record.status,
                    readiness_score=score,
                    readiness_band=qa_result.run_record.readiness_band,
                    issue_count=len(qa_result.issues),
                    output_dir=qa_result.artifact_paths.get("output_dir"),
                    acceptance_passed=accepted,
                )
            )
        except Exception as exc:
            results.append(
                PilotDatasetResult(
                    name=name,
                    input_path=str(input_path),
                    run_id=None,
                    status="failed",
                    readiness_score=None,
                    readiness_band=None,
                    issue_count=None,
                    output_dir=None,
                    acceptance_passed=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    payload = {
        "pilot_version": "v1.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(result.acceptance_passed for result in results),
        "dataset_count": len(results),
        "results": [asdict(result) for result in results],
    }
    (output_path / "pilot_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GeoQA V1.2 three-dataset customer pilot.")
    parser.add_argument("manifest")
    parser.add_argument("--output-root", default="outputs/v1_2_pilot")
    args = parser.parse_args()
    result = run_three_dataset_pilot(args.manifest, args.output_root)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
