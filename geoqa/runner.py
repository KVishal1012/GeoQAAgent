from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import pandas as pd

from geoqa.checks.crs_checks import run_crs_checks
from geoqa.checks.geometry_checks import run_geometry_checks
from geoqa.checks.linear_reference_checks import run_linear_reference_checks
from geoqa.checks.schema_checks import run_schema_checks
from geoqa.checks.sqlserver_checks import run_sqlserver_checks
from geoqa.ingestion.loaders import load_dataset
from geoqa.ingestion.validators import validate_input_file
from geoqa.models import QAResult, RunRecord
from geoqa.normalization.crs_normalizer import normalize_crs
from geoqa.normalization.geometry_normalizer import normalize_geometries
from geoqa.normalization.precision import normalize_precision
from geoqa.ops.run_logger import write_run_log
from geoqa.reporting.report_generator import generate_artifacts
from geoqa.scoring.readiness_score import calculate_readiness_score
from geoqa.severity.taxonomy import apply_severity


def run_geoqa(
    input_path: str,
    output_root: str = "outputs",
    required_columns: list[str] | None = None,
    target_crs: str | None = None,
    precision_grid_size: float | None = None,
    enable_sqlserver_checks: bool = True,
    enable_linear_reference_checks: bool = True,
) -> QAResult:
    run_record = RunRecord(
        run_id=f"geoqa-{uuid4().hex[:12]}",
        input_path=str(Path(input_path).expanduser().resolve()),
        enabled_checks=_build_enabled_checks(enable_sqlserver_checks, enable_linear_reference_checks),
    )
    started = datetime.now(timezone.utc)
    try:
        validated_path = validate_input_file(input_path)
        gdf, metadata = load_dataset(validated_path)
        gdf, feature_id_notes = _ensure_feature_id(gdf)

        run_record.filename = metadata["filename"]
        run_record.feature_count = metadata["feature_count"]
        run_record.geometry_types = metadata["geometry_types"]
        run_record.crs = metadata["crs"]

        gdf, crs_notes = normalize_crs(gdf, target_crs=target_crs)
        gdf, geometry_notes = normalize_geometries(gdf)
        gdf, precision_notes = normalize_precision(gdf, grid_size=precision_grid_size)
        run_record.normalization_notes = feature_id_notes + crs_notes + geometry_notes + precision_notes
        run_record.crs = gdf.crs.to_string() if gdf.crs else run_record.crs
        run_record.geometry_types = sorted({str(value) for value in gdf.geom_type.dropna().unique()})

        issues = []
        issues.extend(run_crs_checks(gdf))
        issues.extend(run_geometry_checks(gdf))
        issues.extend(run_schema_checks(gdf, required_columns=required_columns))
        if enable_sqlserver_checks:
            issues.extend(run_sqlserver_checks(gdf))
        if enable_linear_reference_checks:
            issues.extend(run_linear_reference_checks(gdf))
        issues = apply_severity(issues)

        readiness = calculate_readiness_score(issues)
        run_record.readiness_score = int(readiness["score"])
        run_record.readiness_band = str(readiness["band"])
        run_record.issue_counts = {
            "low": int(readiness["penalties"]["low"]),
            "medium": int(readiness["penalties"]["medium"]),
            "high": int(readiness["penalties"]["high"]),
            "total": len(issues),
        }
        run_record.status = "completed"

        summary = {
            "dataset": {
                "filename": metadata["filename"],
                "feature_count": int(len(gdf)),
                "geometry_types": run_record.geometry_types,
                "crs": run_record.crs,
                "columns": metadata["columns"],
            },
            "readiness": readiness,
        }
        qa_result = QAResult(run_record=run_record, issues=issues, summary=summary)
        qa_result.artifact_paths = generate_artifacts(qa_result, output_root=output_root)
        return qa_result
    except Exception as exc:
        run_record.status = "failed"
        run_record.error = str(exc)
        raise
    finally:
        finished = datetime.now(timezone.utc)
        run_record.finished_at = finished.isoformat()
        run_record.duration_seconds = round((finished - started).total_seconds(), 3)
        write_run_log(run_record, output_root)


def _ensure_feature_id(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, list[str]]:
    if "feature_id" in gdf.columns:
        return gdf, ["Feature IDs retained from existing feature_id column."]

    normalized = gdf.copy()
    source_column = _detect_feature_id_column(normalized)
    if source_column is not None:
        normalized["feature_id"] = normalized[source_column]
        return normalized, [f"Feature IDs copied from source column '{source_column}'."]

    normalized["feature_id"] = [f"feature-{idx}" for idx in range(len(normalized))]
    return normalized, ["Feature IDs generated because no complete unique ID column was detected."]


def _detect_feature_id_column(gdf: gpd.GeoDataFrame) -> str | None:
    candidates: list[tuple[tuple[int, int, str], str]] = []
    for column in gdf.columns:
        if column == gdf.geometry.name:
            continue
        column_name = str(column)
        score = _id_column_score(column_name)
        if score is None:
            continue
        if _is_complete_unique_id(gdf[column]):
            candidates.append((score, column_name))

    if not candidates:
        return None
    return sorted(candidates)[0][1]


def _id_column_score(column_name: str) -> tuple[int, int, str] | None:
    normalized = _normalize_column_name(column_name)
    stripped = normalized.rstrip("0123456789")
    normalized_names = {normalized, stripped}

    if "featureid" in normalized_names:
        return (0, len(column_name), normalized)
    if normalized_names & {"id", "fid", "gid", "uuid", "globalid"}:
        return (10, len(column_name), normalized)
    if normalized_names & {"objectid", "objecti"}:
        return (20, len(column_name), normalized)
    if normalized_names & {"assetid"}:
        return (30, len(column_name), normalized)
    if normalized_names & {"intersectionid", "intersectid", "interse"}:
        return (40, len(column_name), normalized)
    if normalized.endswith("id") or stripped.endswith("id"):
        return (60, len(column_name), normalized)
    return None


def _normalize_column_name(column_name: str) -> str:
    return "".join(character for character in column_name.lower() if character.isalnum())


def _is_complete_unique_id(values: pd.Series) -> bool:
    string_values = values.astype("string").str.strip()
    return bool(string_values.notna().all() and (string_values != "").all() and string_values.is_unique)


def _build_enabled_checks(
    enable_sqlserver_checks: bool,
    enable_linear_reference_checks: bool,
) -> list[str]:
    checks = ["crs_checks", "geometry_checks", "schema_checks"]
    if enable_sqlserver_checks:
        checks.append("sqlserver_checks")
    if enable_linear_reference_checks:
        checks.append("linear_reference_checks")
    return checks
