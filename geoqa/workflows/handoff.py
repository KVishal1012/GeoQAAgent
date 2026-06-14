from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from geoqa.workflows.comparison import load_comparison_index


class HandoffBundleError(RuntimeError):
    """Raised when a handoff bundle cannot be exported safely."""


def export_handoff_bundle(
    run_output_dir: str | Path,
    *,
    include_comparison: bool = True,
    comparison_key: str | None = None,
    bundle_name: str = "handoff_bundle.zip",
) -> dict[str, str | bool]:
    output_path = Path(run_output_dir)
    manifest = build_bundle_manifest(
        output_path,
        include_comparison=include_comparison,
        comparison_key=comparison_key,
    )
    if manifest["blocking_missing"]:
        missing = ", ".join(manifest["blocking_missing"])
        raise HandoffBundleError(f"Cannot export handoff bundle because required artifacts are missing: {missing}")

    manifest_path = output_path / "bundle_manifest.json"
    bundle_path = output_path / bundle_name
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for relative_path in manifest["included_files"]:
            archive.write(output_path / str(relative_path), arcname=str(relative_path))
        archive.write(manifest_path, arcname="bundle_manifest.json")
    return {
        "bundle_manifest": str(manifest_path),
        "handoff_bundle": str(bundle_path),
        "bundle_complete": bool(manifest["complete"]),
    }


def build_bundle_manifest(
    run_output_dir: Path,
    *,
    include_comparison: bool,
    comparison_key: str | None,
) -> dict[str, object]:
    required_files = [
        "qa_report.md",
        "issues.csv",
        "summary.json",
        "run_record.json",
        "geometry_profile.json",
        "customer_report.md",
        "customer_intake.json",
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

    blocking_missing = [name for name in required_files if not (run_output_dir / name).exists()]
    warning_missing: list[str] = []
    included_files = [name for name in required_files + optional_files if (run_output_dir / name).exists()]

    selected_comparison_key = None
    if include_comparison:
        selected_comparison = _resolve_comparison_selection(run_output_dir, comparison_key)
        if selected_comparison is None:
            warning_missing.append("comparison artifacts")
        else:
            selected_comparison_key = str(selected_comparison["comparison_key"])
            for artifact_key in ("summary_path", "report_path"):
                comparison_path = Path(str(selected_comparison[artifact_key]))
                included_files.append(str(comparison_path.relative_to(run_output_dir)))

    return {
        "run_output_dir": str(run_output_dir),
        "complete": not blocking_missing,
        "blocking_missing": blocking_missing,
        "warning_missing": warning_missing,
        "selected_comparison_key": selected_comparison_key,
        "included_files": sorted(dict.fromkeys(included_files)),
    }


def _resolve_comparison_selection(run_output_dir: Path, comparison_key: str | None) -> dict[str, object] | None:
    comparisons = load_comparison_index(run_output_dir)
    if not comparisons:
        return None
    if comparison_key:
        for comparison in comparisons:
            if comparison.get("comparison_key") == comparison_key:
                return comparison
        return None
    return comparisons[0]
