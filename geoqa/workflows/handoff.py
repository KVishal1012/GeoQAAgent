from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def export_handoff_bundle(
    run_output_dir: str | Path,
    *,
    include_comparison: bool = True,
    bundle_name: str = "handoff_bundle.zip",
) -> dict[str, str]:
    output_path = Path(run_output_dir)
    manifest = build_bundle_manifest(output_path, include_comparison=include_comparison)
    manifest_path = output_path / "bundle_manifest.json"
    bundle_path = output_path / bundle_name
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for relative_path in manifest["included_files"]:
            archive.write(output_path / relative_path, arcname=relative_path)
        archive.write(manifest_path, arcname="bundle_manifest.json")
    return {
        "bundle_manifest": str(manifest_path),
        "handoff_bundle": str(bundle_path),
    }


def build_bundle_manifest(run_output_dir: Path, *, include_comparison: bool) -> dict[str, object]:
    required_files = [
        "qa_report.md",
        "issues.csv",
        "summary.json",
        "run_record.json",
        "review_status.json",
        "review_history.jsonl",
        "fix_plan.md",
        "fix_plan.json",
    ]
    optional_files = [
        "agent_report_draft.md",
        "agent_report.md",
        "agent_report.json",
        "report_consistency.json",
        "hallucination_check.json",
    ]
    if include_comparison:
        optional_files.extend(["comparison_summary.json", "comparison_report.md"])

    included_files = [name for name in required_files + optional_files if (run_output_dir / name).exists()]
    return {
        "run_output_dir": str(run_output_dir),
        "included_files": included_files,
    }
