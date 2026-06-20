from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request

from geoqa.config import load_app_config
from geoqa.normalization.crs_normalizer import normalize_target_crs
from geoqa.production.store import ProductionStoreError, build_production_store
from geoqa.reporting.agent_report_generator import read_agent_review_status, review_existing_agent_report
from geoqa.runner import run_geoqa

app = Flask(__name__)

_STATE_LOCK = threading.Lock()
_STATE_ROOT_BY_RUN_ID: dict[str, Path] = {}


@dataclass(slots=True)
class RunState:
    run_id: str
    status: str
    submitted_at: str
    input_path: str
    required_columns: list[str]
    target_crs: str | None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    run_output_dir: str | None = None
    readiness_score: int | None = None
    readiness_band: str | None = None
    issue_counts: dict[str, int] | None = None
    customer_intake: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class APIError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_request_id() -> str:
    return request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"


def _runtime_config():
    return load_app_config()


def _production_store():
    return build_production_store(_runtime_config())


def _output_root() -> Path:
    configured = os.getenv("GEOQA_OUTPUT_ROOT")
    if configured and configured.strip():
        return Path(configured).resolve()
    if os.getenv("VERCEL"):
        return Path("/tmp/geoqa-outputs").resolve()
    return Path("outputs").resolve()


def _state_root() -> Path:
    root = _output_root() / "api_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_state_path(run_id: str) -> Path:
    root = _STATE_ROOT_BY_RUN_ID.get(run_id) or _state_root()
    return root / f"{run_id}.json"


def _write_state(state: RunState) -> None:
    with _STATE_LOCK:
        _STATE_ROOT_BY_RUN_ID.setdefault(state.run_id, _state_root())
        _run_state_path(state.run_id).write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def _read_state(run_id: str) -> RunState:
    path = _run_state_path(run_id)
    if not path.exists():
        raise APIError("run_not_found", f"Run '{run_id}' was not found.", status_code=404)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RunState(**payload)


def _read_state_or_none(run_id: str) -> RunState | None:
    path = _run_state_path(run_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RunState(**payload)


def _update_state(run_id: str, **updates: Any) -> RunState:
    state = _read_state(run_id)
    payload = state.to_dict()
    payload.update(updates)
    next_state = RunState(**payload)
    _write_state(next_state)
    return next_state


def _auth_required() -> bool:
    return request.path.startswith("/api/v1/")


def _validate_api_key() -> None:
    configured = os.getenv("GEOQA_API_KEY")
    if not configured:
        return
    provided = request.headers.get("x-api-key")
    if provided != configured:
        raise APIError("unauthorized", "Missing or invalid API key.", status_code=401)


def _parse_customer_intake(payload: dict[str, Any], required_columns: list[str], target_crs: str | None) -> dict[str, Any]:
    raw = payload.get("customer_intake") if isinstance(payload.get("customer_intake"), dict) else {}
    intake = {
        "customer_name": str(raw.get("customer_name") or payload.get("customer_name") or "").strip(),
        "business_owner": str(raw.get("business_owner") or payload.get("business_owner") or "").strip(),
        "dataset_name": str(raw.get("dataset_name") or payload.get("customer_dataset_name") or payload.get("dataset_name") or "").strip(),
        "intended_use": str(raw.get("intended_use") or payload.get("intended_use") or "").strip(),
        "decision_context": str(raw.get("decision_context") or payload.get("decision_context") or "").strip(),
        "notes": str(raw.get("notes") or payload.get("customer_notes") or payload.get("notes") or "").strip(),
        "required_columns": required_columns,
        "target_crs": target_crs,
    }
    return {key: value for key, value in intake.items() if value not in ("", None, [])}

def _parse_required_columns(raw_columns: Any) -> list[str]:
    if raw_columns in (None, ""):
        return []
    if isinstance(raw_columns, str):
        return [value.strip() for value in raw_columns.split(",") if value.strip()]
    if not isinstance(raw_columns, list):
        raise APIError("validation_error", "required_columns must be a list of strings.", details={"field": "required_columns"})
    return [str(value).strip() for value in raw_columns if str(value).strip()]


def _parse_target_crs(raw_value: Any) -> str | None:
    try:
        return normalize_target_crs(raw_value)
    except ValueError as exc:
        raise APIError("validation_error", str(exc), details={"field": "target_crs"}) from exc


def _parse_run_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    required_columns = _parse_required_columns(payload.get("required_columns") or [])
    target_crs = _parse_target_crs(payload.get("target_crs") or payload.get("target_srid") or payload.get("srid"))

    upload_id = str(payload.get("upload_id") or "").strip()
    upload_storage_path = str(payload.get("upload_storage_path") or payload.get("storage_path") or "").strip()
    filename = str(payload.get("filename") or "").strip()
    size_bytes = payload.get("size_bytes")
    content_type = payload.get("content_type")
    customer_intake = _parse_customer_intake(payload, required_columns, target_crs)
    if upload_id or upload_storage_path:
        if not upload_id:
            raise APIError("validation_error", "upload_id is required.", details={"field": "upload_id"})
        if not upload_storage_path:
            raise APIError("validation_error", "upload_storage_path is required.", details={"field": "upload_storage_path"})
        if not filename:
            raise APIError("validation_error", "filename is required.", details={"field": "filename"})
        return {
            "mode": "uploaded",
            "upload_id": upload_id,
            "upload_storage_path": upload_storage_path,
            "filename": filename,
            "required_columns": required_columns,
            "target_crs": target_crs,
            "size_bytes": int(size_bytes) if size_bytes not in (None, "") else None,
            "content_type": str(content_type).strip() if content_type else None,
            "customer_intake": customer_intake,
        }

    input_path = str(payload.get("input_path") or "").strip()
    if not input_path:
        raise APIError("validation_error", "input_path or uploaded file metadata is required.", details={"field": "input_path"})
    if not Path(input_path).exists():
        raise APIError("input_not_found", f"input_path does not exist: {input_path}", status_code=404)
    return {
        "mode": "local_input_path",
        "input_path": input_path,
        "required_columns": required_columns,
        "target_crs": target_crs,
    }


def _launch_run_async(run_id: str) -> None:
    thread = threading.Thread(target=_execute_run, args=(run_id,), daemon=True)
    thread.start()


def _execute_run(run_id: str) -> None:
    try:
        state = _update_state(run_id, status="running", started_at=_utc_now())
        result = run_geoqa(
            input_path=state.input_path,
            output_root=str(_output_root()),
            required_columns=state.required_columns,
            target_crs=state.target_crs,
            customer_intake=state.customer_intake or {},
        )
        _update_state(
            run_id,
            status="completed",
            finished_at=_utc_now(),
            run_output_dir=result.artifact_paths.get("output_dir"),
            readiness_score=result.run_record.readiness_score,
            readiness_band=result.run_record.readiness_band,
            issue_counts=result.issue_counts,
            error=None,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        _update_state(run_id, status="failed", finished_at=_utc_now(), error=str(exc))



def _enrich_run_payload_with_artifacts(payload: dict[str, Any]) -> dict[str, Any]:
    output_dir = payload.get("run_output_dir")
    if not output_dir:
        return payload
    summary_path = Path(str(output_dir)) / "summary.json"
    if not summary_path.exists():
        return payload
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    dataset = summary.get("dataset") or {}
    payload.setdefault("geometry_types", dataset.get("geometry_types"))
    payload.setdefault("geometry_profile", dataset.get("geometry_profile"))
    payload.setdefault("spatial_anomalies", summary.get("spatial_anomalies"))
    return payload

def _response(payload: dict[str, Any], status_code: int = 200) -> Response:
    payload["request_id"] = g.request_id
    return jsonify(payload), status_code


def _error_response(error: APIError) -> Response:
    return (
        jsonify(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details or None,
                },
                "request_id": g.request_id,
            }
        ),
        error.status_code,
    )


def _store_error(exc: ProductionStoreError, *, status_code: int = 400) -> APIError:
    return APIError("production_store_error", str(exc), status_code=status_code)


def _landing_page_html() -> str:
    config = _runtime_config()
    has_api_key = bool(os.getenv("GEOQA_API_KEY"))
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    llm_model = os.getenv("GEOQA_LLM_MODEL") or "not configured"
    storage_status = "Supabase" if config.supabase_url and config.supabase_service_role_key else "Local fallback"
    api_status = "Protected" if has_api_key else "Open setup"
    openai_status = "Configured" if has_openai_key else "Not configured"
    max_upload = config.large_file_max_upload_mb if config.large_file_mode else config.max_upload_mb
    upload_mode = "Direct Supabase upload" if config.supabase_url and config.supabase_service_role_key else "Local fallback upload"
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GeoQA Data Readiness Audit</title>
  <style>
    :root {
      --ink: #17231d;
      --muted: #65736b;
      --soft: #f4f7f1;
      --paper: #fffdf7;
      --panel: #fbfaf3;
      --line: #d9e1d6;
      --green: #1f6b4f;
      --green-2: #0f4c39;
      --steel: #3b6674;
      --amber: #c8812d;
      --red: #a63d32;
      --shadow: rgba(23, 35, 29, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Aptos", "Segoe UI", ui-sans-serif, system-ui, sans-serif;
      color: var(--ink);
      background:
        linear-gradient(135deg, rgba(31,107,79,.08), transparent 32%),
        linear-gradient(180deg, #fcfdf8 0%, #edf3e9 100%);
    }
    button, input, select, textarea { font: inherit; }
    button { border: 0; border-radius: 8px; padding: 10px 13px; background: var(--green); color: white; font-weight: 800; cursor: pointer; }
    button.secondary { background: #e4ede4; color: var(--green-2); }
    button.ghost { background: transparent; color: var(--green-2); border: 1px solid var(--line); }
    button.danger { background: #f2ded9; color: var(--red); }
    button:disabled { opacity: .5; cursor: not-allowed; }
    input, select, textarea { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 10px 11px; color: var(--ink); background: white; }
    input[type="file"] { border-style: dashed; background: #f7fbf3; padding: 15px; }
    textarea { min-height: 72px; resize: vertical; }
    label { display: block; margin: 11px 0 6px; font-weight: 760; font-size: 13px; }
    .shell { width: min(1380px, calc(100% - 28px)); margin: 0 auto; padding: 18px 0 34px; }
    .topbar { display: grid; grid-template-columns: 1fr auto; gap: 16px; align-items: center; padding: 14px 0 18px; }
    .brand { display: flex; gap: 12px; align-items: center; }
    .mark { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 9px; background: var(--green-2); color: #f7fff5; font-weight: 900; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 2px; font-size: 24px; line-height: 1.1; }
    h2 { margin-bottom: 12px; font-size: 17px; }
    h3 { margin-bottom: 8px; font-size: 14px; }
    p { color: var(--muted); line-height: 1.5; }
    .subtitle { margin: 0; font-size: 13px; }
    .top-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 6px 9px; background: #e7eee6; color: var(--green-2); font-size: 12px; font-weight: 800; }
    .pill.amber { background: #f7ead7; color: #855016; }
    .panel { background: rgba(255,253,247,.94); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 14px 44px var(--shadow); }
    .panel-body { padding: 18px; }
    .console { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(330px, .75fr); gap: 14px; }
    .evidence-grid { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(310px, .75fr); gap: 14px; }
    .map-panel { min-height: 360px; position: relative; overflow: hidden; background: linear-gradient(145deg, #e9f1e6 0%, #f9fbf5 100%); }
    .map-toolbar { position: absolute; z-index: 3; left: 16px; top: 14px; display: flex; gap: 6px; }
    .seg { border: 1px solid rgba(31,107,79,.22); background: rgba(255,255,255,.86); color: var(--green-2); padding: 7px 9px; border-radius: 999px; font-size: 12px; font-weight: 800; }
    .map-canvas { position: absolute; inset: 0; }
    .gridline { position: absolute; background: rgba(59,102,116,.13); }
    .gridline.v1 { left: 18%; top: 0; bottom: 0; width: 1px; } .gridline.v2 { left: 43%; top: 0; bottom: 0; width: 1px; } .gridline.v3 { left: 70%; top: 0; bottom: 0; width: 1px; }
    .gridline.h1 { top: 24%; left: 0; right: 0; height: 1px; } .gridline.h2 { top: 52%; left: 0; right: 0; height: 1px; } .gridline.h3 { top: 78%; left: 0; right: 0; height: 1px; }
    .route { position: absolute; height: 3px; background: var(--steel); opacity: .72; border-radius: 4px; transform-origin: left center; }
    .r1 { left: 16%; top: 54%; width: 310px; transform: rotate(-12deg); } .r2 { left: 22%; top: 45%; width: 230px; transform: rotate(22deg); }
    .r3 { left: 27%; top: 63%; width: 260px; transform: rotate(7deg); } .r4 { left: 34%; top: 38%; width: 170px; transform: rotate(88deg); }
    .cluster { position: absolute; left: 26%; top: 48%; width: 168px; height: 118px; border: 1px solid rgba(31,107,79,.2); border-radius: 50%; background: rgba(31,107,79,.08); }
    .outlier { position: absolute; right: 16%; top: 18%; width: 15px; height: 15px; border-radius: 50%; background: var(--red); box-shadow: 0 0 0 8px rgba(166,61,50,.14); }
    .callout { position: absolute; right: 7%; top: 25%; max-width: 220px; padding: 10px 11px; border-radius: 8px; background: rgba(255,253,247,.95); border: 1px solid #efc7bd; color: var(--red); font-size: 12px; font-weight: 800; }
    .map-empty { position: absolute; left: 20px; right: 20px; bottom: 18px; padding: 12px; border: 1px dashed var(--line); border-radius: 8px; background: rgba(255,255,255,.78); color: var(--muted); }
    .chip-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
    .chip { display: inline-flex; border: 1px solid var(--line); background: var(--soft); padding: 6px 8px; border-radius: 999px; font-size: 12px; font-weight: 800; color: var(--green-2); }
    .decision { display: grid; gap: 10px; }
    .score { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: center; }
    .score-ring { width: 104px; height: 104px; display: grid; place-items: center; border-radius: 50%; background: conic-gradient(var(--amber) 0deg 256deg, #e8eee5 256deg); }
    .score-ring span { display: grid; place-items: center; width: 78px; height: 78px; border-radius: 50%; background: var(--paper); font-size: 24px; font-weight: 900; color: var(--green-2); }
    .metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .metric { padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #f7faf4; }
    .metric strong { display: block; font-size: 20px; }
    .metric span { color: var(--muted); font-size: 12px; }
    .new-run { display: none; margin-bottom: 14px; }
    .new-run.open { display: block; }
    .form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 12px; }
    .wide { grid-column: span 2; }
    .full { grid-column: 1 / -1; }
    .message { min-height: 22px; margin-top: 10px; font-weight: 800; color: var(--green-2); }
    .message.error { color: var(--red); }
    .delivery { display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, .65fr); gap: 14px; margin-top: 14px; }
    .report-preview { min-height: 308px; }
    .report-section { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
    .triage { margin-top: 14px; overflow: hidden; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; color: var(--muted); background: #f3f7f0; padding: 10px; border-bottom: 1px solid var(--line); }
    td { padding: 11px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
    .severity { font-weight: 900; color: var(--green-2); }
    .severity.high { color: var(--red); } .severity.medium { color: var(--amber); }
    .package-list { display: grid; gap: 8px; }
    .package-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdf8; }
    .package-row a { color: var(--green-2); font-weight: 900; text-decoration: none; }
    .status-note { font-size: 12px; font-weight: 850; color: var(--muted); }
    .status-note.ready { color: var(--green-2); }
    .review-box { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 14px; }
    .review-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .recent { display: grid; gap: 8px; max-height: 180px; overflow: auto; }
    .recent button { padding: 7px 9px; }
    details { margin-top: 12px; }
    summary { cursor: pointer; color: var(--green-2); font-weight: 900; }
    .secondary-links a { display: inline-block; margin: 6px 7px 0 0; color: var(--green-2); font-weight: 850; text-decoration: none; }
    .raw { display: none; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; padding: 12px; background: #14221b; color: #ecf5ec; border-radius: 8px; }
    @media (max-width: 1060px) { .console, .evidence-grid, .delivery { grid-template-columns: 1fr; } .form-grid { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 680px) { .shell { width: min(100% - 18px, 1380px); } .topbar { grid-template-columns: 1fr; } .top-actions { justify-content: flex-start; } .form-grid { grid-template-columns: 1fr; } .wide { grid-column: auto; } .metric-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="mark">GQ</div>
        <div>
          <h1>GeoQA Data Readiness Audit</h1>
          <p class="subtitle">Evidence Package Console for geospatial upload, QA review, and customer handoff.</p>
        </div>
      </div>
      <div class="top-actions">
        <span class="pill" id="topRunStatus">No active run</span>
        <span class="pill">API __API_STATUS__</span>
        <span class="pill">Storage __STORAGE_STATUS__</span>
        <span class="pill amber">Worker async</span>
        <button id="newRunButton">New run</button>
        <button id="refreshRun" class="secondary" disabled>Refresh status</button>
      </div>
    </header>

    <section id="newRunPanel" class="panel new-run">
      <div class="panel-body">
        <h2>New run</h2>
        <p class="subtitle">Upload GeoJSON, GeoPackage, or zipped shapefile. Max upload: __MAX_UPLOAD__ MB. Upload mode: __UPLOAD_MODE__.</p>
        <div class="form-grid">
          <div><label for="apiKey">API key, if configured</label><input id="apiKey" type="password" placeholder="Paste x-api-key for protected deployments" /></div>
          <div class="wide"><label for="dataset">Dataset file</label><input id="dataset" type="file" accept=".geojson,.gpkg,.zip,application/zip" /></div>
          <div><label for="customerName">Customer / organization</label><input id="customerName" type="text" placeholder="City GIS Team" /></div>
          <div><label for="businessOwner">Business owner</label><input id="businessOwner" type="text" placeholder="GIS manager" /></div>
          <div><label for="customerDatasetName">Business dataset name</label><input id="customerDatasetName" type="text" placeholder="Road centreline intersections" /></div>
          <div><label for="intendedUse">Intended downstream use</label><select id="intendedUse"><option value="">General QA / not specified</option><option value="sql_load">SQL/database loading</option><option value="dashboard">Dashboard or reporting</option><option value="migration">GIS or asset-system migration</option><option value="routing">Routing or network analysis</option><option value="asset_handoff">Asset handoff</option><option value="spatial_join">Spatial joins or enrichment</option><option value="other">Other downstream use</option></select></div>
          <div><label for="requiredColumns">Required columns, optional</label><input id="requiredColumns" type="text" placeholder="asset_id, road_name" /></div>
          <div><label for="targetCrs">Target CRS / SRID</label><input id="targetCrs" type="text" list="crsPresets" placeholder="Keep source CRS, or enter EPSG:4326 / 3857" /><datalist id="crsPresets"><option value="EPSG:4326">WGS 84 longitude/latitude</option><option value="EPSG:3857">Web Mercator</option><option value="4326">SRID 4326</option><option value="3857">SRID 3857</option></datalist></div>
          <div class="wide"><label for="decisionContext">Decision context</label><input id="decisionContext" type="text" placeholder="Approve SQL load before migration" /></div>
          <div class="full"><label for="customerNotes">Customer notes</label><textarea id="customerNotes" placeholder="What decision should this audit support?"></textarea></div>
        </div>
        <div class="review-actions"><button id="submitRun">Upload and queue QA</button><button id="closeNewRun" class="ghost">Close</button></div>
        <div id="message" class="message"></div>
      </div>
    </section>

    <section class="console">
      <div class="evidence-grid">
        <section class="panel map-panel" aria-label="Spatial evidence">
          <div class="map-toolbar"><span class="seg">Geometry</span><span class="seg">Anomalies</span><span class="seg">Findings</span></div>
          <div class="map-canvas" id="mapPanel">
            <div class="gridline v1"></div><div class="gridline v2"></div><div class="gridline v3"></div><div class="gridline h1"></div><div class="gridline h2"></div><div class="gridline h3"></div>
            <div class="route r1"></div><div class="route r2"></div><div class="route r3"></div><div class="route r4"></div><div class="cluster"></div><div class="outlier"></div>
            <div class="callout" id="anomalyCallout">Evidence preview appears after QA completes.</div>
            <div class="map-empty" id="mapEmpty">Spatial evidence uses GeoQA summary metadata first: geometry type, CRS, feature count, and spatial anomaly count.</div>
          </div>
        </section>

        <aside class="panel">
          <div class="panel-body decision">
            <h2>Readiness decision</h2>
            <div class="score"><div class="score-ring"><span id="readinessScore">--</span></div><div><strong id="readinessBand">Waiting for run</strong><p id="decisionText">Upload a dataset or open a recent run to review readiness evidence.</p></div></div>
            <div class="metric-grid"><div class="metric"><strong id="issueHigh">-</strong><span>High</span></div><div class="metric"><strong id="issueMedium">-</strong><span>Medium</span></div><div class="metric"><strong id="issueLow">-</strong><span>Low</span></div></div>
            <div class="chip-row" id="evidenceChips"><span class="chip">No evidence loaded</span></div>
            <div class="status"><span class="label">Run ID</span><span id="runId" class="value">Not started</span></div>
            <div class="status"><span class="label">Status</span><span id="runStatus" class="value">Waiting</span></div>
            <div class="status"><span class="label">Current run</span><span id="currentFilename" class="value">-</span></div>
            <h3>Recent runs</h3>
            <div id="recentRuns" class="recent"><p class="subtitle">Recent production runs load after page startup.</p></div>
          </div>
        </aside>
      </div>

      <aside class="panel">
        <div class="panel-body">
          <h2>Audit package</h2>
          <div id="primaryArtifacts" class="package-list"></div>
          <div class="review-box">
            <h3>Reviewer gate</h3>
            <label for="reviewerName">Reviewer name</label><input id="reviewerName" type="text" placeholder="QA Reviewer" />
            <label for="reviewNotes">Review notes</label><textarea id="reviewNotes" placeholder="Approval or rejection notes"></textarea>
            <div class="review-actions"><button id="approvePackage" disabled>Approve package</button><button id="rejectPackage" class="danger" disabled>Reject</button></div>
            <p id="reviewStatus" class="subtitle">Review is available when an AI draft exists for a completed run.</p>
          </div>
          <details><summary>Secondary artifacts</summary><div id="secondaryArtifacts" class="secondary-links"></div></details>
        </div>
      </aside>
    </section>

    <section class="delivery">
      <section class="panel report-preview"><div class="panel-body" id="reportPreview"><h2>Customer report preview</h2><p>Open or complete a run to preview the customer-facing audit narrative.</p></div></section>
      <section class="panel triage"><div class="panel-body"><h2>Issue triage</h2><table><thead><tr><th>Severity</th><th>Finding</th><th>Affected record/column</th><th>Why it matters</th><th>Suggested action</th></tr></thead><tbody id="triageBody"><tr><td colspan="5">Issue triage appears after QA completes. Use Issues CSV for record-level detail.</td></tr></tbody></table></div></section>
    </section>
    <pre id="raw" class="raw">{}</pre>
  </main>
  <script>
    let currentRunId = null;
    let currentRunPayload = null;
    let currentArtifacts = {};
    let pollTimer = null;
    const $ = (id) => document.getElementById(id);
    const primaryArtifactOrder = ["customer_report_pdf", "issues_csv", "handoff_bundle"];
    const secondaryArtifactOrder = ["qa_report", "summary", "run_record", "geometry_profile", "customer_report", "customer_intake", "review_status", "review_history", "agent_report_draft", "agent_report", "agent_report_json", "agent_session", "agent_trace", "report_consistency", "hallucination_check", "fix_plan", "fix_plan_json", "bundle_manifest"];
    const artifactLabels = { customer_report_pdf: "Customer report PDF", issues_csv: "Issues CSV", handoff_bundle: "Handoff bundle", qa_report: "QA report", summary: "Summary JSON", run_record: "Run record JSON", geometry_profile: "Geometry profile JSON", customer_report: "Customer report Markdown", customer_intake: "Customer intake JSON", review_status: "Review status", review_history: "Review history", agent_report_draft: "AI draft report", agent_report: "AI final report", agent_report_json: "AI report metadata", agent_session: "Agent session", agent_trace: "Agent trace", report_consistency: "Report consistency", hallucination_check: "Hallucination check", fix_plan: "Fix plan", fix_plan_json: "Fix plan JSON", bundle_manifest: "Bundle manifest" };
    function headers(json = false) { const value = $("apiKey").value.trim(); const output = {}; if (value) output["x-api-key"] = value; if (json) output["Content-Type"] = "application/json"; return output; }
    function setMessage(text, isError = false) { $("message").textContent = text; $("message").className = "message" + (isError ? " error" : ""); }
    async function readJson(response) { const payload = await response.json(); if (!response.ok) { const error = payload.error || {}; throw new Error(error.message || "Request failed"); } return payload; }
    function titleCase(value) { return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()); }
    function renderPackageRows() {
      $("primaryArtifacts").innerHTML = primaryArtifactOrder.map((name) => {
        const artifact = currentArtifacts[name] || {};
        const label = artifactLabels[name] || name;
        if (artifact.exists && artifact.url) return `<div class="package-row"><a href="${artifact.url}" target="_blank" rel="noopener">${label}</a><span class="status-note ready">Ready</span></div>`;
        return `<div class="package-row"><span>${label}</span><span class="status-note">${name === "handoff_bundle" ? "Not generated yet" : "Pending"}</span></div>`;
      }).join("");
      $("secondaryArtifacts").innerHTML = secondaryArtifactOrder.map((name) => {
        const artifact = currentArtifacts[name] || {};
        if (!artifact.exists || !artifact.url) return "";
        return `<a href="${artifact.url}" target="_blank" rel="noopener">${artifactLabels[name] || name}</a>`;
      }).join("") || "<p class='subtitle'>Secondary artifacts appear after QA completes.</p>";
    }
    function renderEvidence(payload) {
      const profile = payload.geometry_profile || {};
      const dataset = payload.dataset || {};
      const anomalies = payload.spatial_anomalies || {};
      const geometry = profile.primary_geometry_label || (payload.geometry_types || []).join(", ") || "Geometry pending";
      const crs = payload.crs || dataset.crs || profile.crs || payload.target_crs || "CRS pending";
      const featureCount = payload.feature_count || dataset.feature_count || "Feature count pending";
      const anomalyCount = anomalies.count ?? 0;
      $("evidenceChips").innerHTML = [`<span class="chip">${geometry}</span>`, `<span class="chip">${crs}</span>`, `<span class="chip">${featureCount} features</span>`, `<span class="chip">${anomalyCount} spatial anomalies</span>`].join("");
      $("anomalyCallout").textContent = payload.status === "completed" ? (anomalyCount ? `Spatial anomaly: ${anomalyCount} flagged` : "No strong spatial outliers detected") : "Evidence preview appears after QA completes.";
      $("mapEmpty").textContent = payload.status === "completed" ? `Spatial evidence: ${geometry}, ${crs}.` : "Evidence preview appears after QA completes.";
    }
    function renderReportPreview(payload) {
      const band = titleCase(payload.readiness_band || "Pending");
      const score = payload.readiness_score ?? "--";
      const filename = payload.filename || "No dataset selected";
      const profile = payload.geometry_profile || {};
      const anomalies = payload.spatial_anomalies || {};
      $("reportPreview").innerHTML = `<h2>GeoQA Data Readiness Audit</h2><p><strong>${filename}</strong></p><div class="chip-row"><span class="chip">${score}/100</span><span class="chip">${band}</span><span class="chip">${profile.primary_geometry_label || "Geometry pending"}</span><span class="chip">${anomalies.count ?? 0} spatial outliers</span></div><div class="report-section"><h3>Executive Summary</h3><p>${decisionFor(payload)}</p></div><div class="report-section"><h3>Geometry Profile</h3><p>${profile.primary_geometry_label || "Geometry profile appears after QA completes."}</p></div><div class="report-section"><h3>Recommended Fixes</h3><p>Use the issue triage table and Issues CSV for evidence-backed remediation.</p></div>`;
    }
    function decisionFor(payload) {
      if (payload.status !== "completed") return "Run the deterministic QA pipeline to produce an evidence-backed readiness decision.";
      const band = payload.readiness_band || "needs_review";
      const anomalies = payload.spatial_anomalies || {};
      if (band === "ready") return "Ready for review before handoff. Keep the QA artifacts with the downstream package.";
      if ((anomalies.count || 0) > 0) return "Review spatial anomaly findings before loading, joining, migration, or handoff.";
      return "Review duplicate geometry, schema, and compatibility findings before loading or handoff.";
    }
    function renderTriage(payload) {
      if (payload.status !== "completed") { $("triageBody").innerHTML = `<tr><td colspan="5">Issue triage appears after QA completes. Use Issues CSV for record-level detail.</td></tr>`; return; }
      const counts = payload.issue_counts || {};
      const anomalies = payload.spatial_anomalies || {};
      const rows = [];
      if ((counts.high || 0) > 0) rows.push(["high", "High-severity QA findings", `${counts.high} finding(s)`, "High-severity records can block loading, joins, or trusted reporting.", "Open Issues CSV and resolve or approve each high finding."]);
      if ((counts.medium || 0) > 0) rows.push(["medium", "Medium-severity QA findings", `${counts.medium} finding(s)`, "Medium findings may create downstream review or cleanup work.", "Review before migration, reporting, or handoff."]);
      if ((anomalies.count || 0) > 0) rows.push(["medium", "Spatial outlier", `${anomalies.count} feature(s)`, "A feature far from the main cluster can break spatial joins, maps, or summaries.", "Confirm whether the outlier belongs in this dataset."]);
      if (!rows.length) rows.push(["low", "No blocking summary findings", "Dataset summary", "The summary-level view did not identify a blocking issue.", "Download Issues CSV for record-level evidence."]);
      $("triageBody").innerHTML = rows.map((row) => `<tr><td class="severity ${row[0]}">${titleCase(row[0])}</td><td>${row[1]}</td><td>${row[2]}</td><td>${row[3]}</td><td>${row[4]}</td></tr>`).join("");
    }
    function renderReview(payload) {
      const status = payload.review_status || {};
      const reviewable = payload.status === "completed" && status && ["draft_ready", "rejected", "approved"].includes(status.status);
      $("reviewStatus").textContent = status.status ? `Review status: ${titleCase(status.status)}` : "Review is available when an AI draft exists for a completed run.";
      $("approvePackage").disabled = !reviewable || status.status === "approved";
      $("rejectPackage").disabled = !reviewable;
    }
    function renderRun(payload) {
      currentRunPayload = payload;
      $("raw").textContent = JSON.stringify(payload, null, 2);
      currentRunId = payload.run_id || currentRunId;
      const counts = payload.issue_counts || {};
      $("runId").textContent = currentRunId || "Not started";
      $("runStatus").textContent = payload.status || "Waiting";
      $("topRunStatus").textContent = payload.status ? `Run ${payload.status}` : "No active run";
      $("currentFilename").textContent = payload.filename || "-";
      $("readinessScore").textContent = payload.readiness_score ?? "--";
      $("readinessBand").textContent = titleCase(payload.readiness_band || "Waiting for run");
      $("decisionText").textContent = decisionFor(payload);
      $("issueHigh").textContent = counts.high ?? "-"; $("issueMedium").textContent = counts.medium ?? "-"; $("issueLow").textContent = counts.low ?? "-";
      renderEvidence(payload); renderReportPreview(payload); renderTriage(payload); renderReview(payload);
    }
    async function loadArtifacts(runId) {
      const response = await fetch(`/api/v1/runs/${runId}/artifacts`, { headers: headers() });
      if (!response.ok) { currentArtifacts = {}; renderPackageRows(); return; }
      const payload = await response.json(); currentArtifacts = payload.artifacts || {}; renderPackageRows();
    }
    async function loadRecentRuns() {
      const response = await fetch("/api/v1/runs?limit=5", { headers: headers() }); if (!response.ok) return;
      const payload = await response.json(); const rows = payload.runs || [];
      if (!rows.length) { $("recentRuns").innerHTML = "<p class='subtitle'>No production runs yet.</p>"; return; }
      $("recentRuns").innerHTML = rows.map((run) => `<div class="package-row"><span><strong>${run.filename || run.run_id}</strong><br><span class="status-note">${run.status} / ${run.readiness_band || "pending"}</span></span><button class="secondary" onclick="openRun('${run.run_id}')">Open</button></div>`).join("");
    }
    async function openRun(runId) { currentRunId = runId; $("refreshRun").disabled = false; await refreshRun(); }
    async function uploadDatasetFile(file) {
      const initResponse = await fetch("/api/v1/uploads/init", { method: "POST", headers: headers(true), body: JSON.stringify({ filename: file.name, size_bytes: file.size, content_type: file.type || "application/octet-stream" }) });
      const session = await readJson(initResponse);
      if (!session.direct_upload) { const form = new FormData(); form.append("file", file); const uploadResponse = await fetch(session.fallback_upload_url || "/api/v1/uploads", { method: "POST", headers: headers(), body: form }); return await readJson(uploadResponse); }
      setMessage(file.size > 6 * 1024 * 1024 ? "Uploading large file to Supabase Storage..." : "Uploading directly to Supabase Storage...");
      const uploadResponse = await fetch(session.upload_url, { method: session.upload_method || "PUT", headers: session.upload_headers || {}, body: file });
      if (!uploadResponse.ok) {
        let details = "";
        try { details = await uploadResponse.text(); } catch (_) { details = ""; }
        throw new Error(details ? `Direct storage upload failed: ${details}` : "Direct storage upload failed.");
      }
      const completeResponse = await fetch("/api/v1/uploads/complete", { method: "POST", headers: headers(true), body: JSON.stringify({ upload_id: session.upload_id, filename: session.filename, storage_path: session.storage_path, size_bytes: file.size, content_type: file.type || "application/octet-stream" }) });
      return await readJson(completeResponse);
    }
    async function refreshRun() {
      if (!currentRunId) return;
      const response = await fetch(`/api/v1/runs/${currentRunId}`, { headers: headers() }); const payload = await readJson(response); renderRun(payload);
      if (payload.status === "completed") { clearInterval(pollTimer); await loadArtifacts(currentRunId); setMessage("Run completed. Audit package artifacts are ready."); }
      else if (payload.status === "failed") { clearInterval(pollTimer); setMessage(payload.error || "Run failed.", true); }
      else setMessage("Run is queued or running. Keep this page open.");
    }
    async function reviewRun(action) {
      if (!currentRunId) return;
      try {
        const reviewer = $("reviewerName").value.trim(); if (!reviewer) throw new Error("Reviewer name is required.");
        const response = await fetch(`/api/v1/runs/${currentRunId}/review`, { method: "POST", headers: headers(true), body: JSON.stringify({ action, reviewer_name: reviewer, notes: $("reviewNotes").value.trim() }) });
        const payload = await readJson(response); setMessage(`Package ${action} recorded.`); await refreshRun(); await loadArtifacts(currentRunId); $("reviewStatus").textContent = `Review status: ${titleCase(payload.review_status?.status || action)}`;
      } catch (error) { setMessage(error.message, true); }
    }
    $("newRunButton").addEventListener("click", () => $("newRunPanel").classList.toggle("open"));
    $("closeNewRun").addEventListener("click", () => $("newRunPanel").classList.remove("open"));
    $("refreshRun").addEventListener("click", refreshRun);
    $("approvePackage").addEventListener("click", () => reviewRun("approve"));
    $("rejectPackage").addEventListener("click", () => reviewRun("reject"));
    $("submitRun").addEventListener("click", async () => {
      try {
        const file = $("dataset").files[0]; if (!file) throw new Error("Choose a dataset file first.");
        $("submitRun").disabled = true; setMessage("Preparing upload..."); const upload = await uploadDatasetFile(file); setMessage("Upload complete. Queueing QA run...");
        const requiredColumns = $("requiredColumns").value.split(",").map((value) => value.trim()).filter(Boolean); const targetCrs = $("targetCrs").value.trim() || null;
        const customerIntake = { customer_name: $("customerName").value.trim(), business_owner: $("businessOwner").value.trim(), dataset_name: $("customerDatasetName").value.trim(), intended_use: $("intendedUse").value.trim(), decision_context: $("decisionContext").value.trim(), notes: $("customerNotes").value.trim() };
        const runResponse = await fetch("/api/v1/runs", { method: "POST", headers: headers(true), body: JSON.stringify({ upload_id: upload.upload_id, upload_storage_path: upload.storage_path, filename: upload.filename, required_columns: requiredColumns, target_crs: targetCrs, target_srid: targetCrs, customer_intake: customerIntake }) });
        const run = await readJson(runResponse); currentRunId = run.run_id; currentArtifacts = {}; renderPackageRows(); $("refreshRun").disabled = false; $("newRunPanel").classList.remove("open"); renderRun(run); setMessage("Run queued. Worker will process it asynchronously."); await loadRecentRuns(); clearInterval(pollTimer); pollTimer = setInterval(refreshRun, 3000);
      } catch (error) { setMessage(error.message, true); } finally { $("submitRun").disabled = false; }
    });
    renderPackageRows(); renderRun({}); loadRecentRuns();
  </script>
</body>
</html>"""
    return (
        html.replace("__API_STATUS__", api_status)
        .replace("__STORAGE_STATUS__", storage_status)
        .replace("__MAX_UPLOAD__", str(max_upload))
        .replace("__UPLOAD_MODE__", upload_mode)
        .replace("__OPENAI_STATUS__", openai_status)
        .replace("__LLM_MODEL__", llm_model)
    )

def _artifact_manifest(output_dir: Path, run_id: str | None = None) -> dict[str, Any]:
    artifact_map = {
        "qa_report": output_dir / "qa_report.md",
        "issues_csv": output_dir / "issues.csv",
        "run_record": output_dir / "run_record.json",
        "summary": output_dir / "summary.json",
        "geometry_profile": output_dir / "geometry_profile.json",
        "customer_report": output_dir / "customer_report.md",
        "customer_report_pdf": output_dir / "customer_report.pdf",
        "customer_intake": output_dir / "customer_intake.json",
        "agent_report_draft": output_dir / "agent_report_draft.md",
        "agent_report": output_dir / "agent_report.md",
        "agent_report_json": output_dir / "agent_report.json",
        "agent_session": output_dir / "agent_session.json",
        "agent_trace": output_dir / "agent_trace.json",
        "report_consistency": output_dir / "report_consistency.json",
        "hallucination_check": output_dir / "hallucination_check.json",
        "review_status": output_dir / "review_status.json",
        "review_history": output_dir / "review_history.jsonl",
        "fix_plan": output_dir / "fix_plan.md",
        "fix_plan_json": output_dir / "fix_plan.json",
        "bundle_manifest": output_dir / "bundle_manifest.json",
        "handoff_bundle": output_dir / "handoff_bundle.zip",
    }
    artifacts: dict[str, Any] = {}
    for name, path in artifact_map.items():
        exists = path.exists()
        artifacts[name] = {
            "path": str(path),
            "exists": exists,
            "url": f"/api/v1/runs/{run_id}/artifacts/{name}/download" if exists and run_id else None,
        }
    return artifacts


@app.before_request
def _before_request() -> None:
    g.request_id = _new_request_id()
    if _auth_required():
        _validate_api_key()


@app.errorhandler(APIError)
def _handle_api_error(error: APIError) -> Response:
    return _error_response(error)


@app.errorhandler(Exception)
def _handle_unexpected_error(error: Exception) -> Response:
    if request.path.startswith("/api/v1/"):
        api_error = APIError("internal_error", "Unexpected server error.", status_code=500, details={"exception": type(error).__name__})
        return _error_response(api_error)
    raise error


@app.get("/")
def root() -> Any:
    return Response(_landing_page_html(), mimetype="text/html")


@app.get("/health")
def health() -> Any:
    return _response({"status": "healthy"})


@app.get("/config")
def config() -> Any:
    runtime = _runtime_config()
    return _response(
        {
            "agent_report_enabled": os.getenv("GEOQA_AGENT_REPORT_ENABLED", "true"),
            "has_openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
            "llm_model": os.getenv("GEOQA_LLM_MODEL"),
            "output_root": str(_output_root()),
            "has_api_key": bool(os.getenv("GEOQA_API_KEY")),
            "supabase_configured": bool(runtime.supabase_url and runtime.supabase_service_role_key),
            "upload_bucket": runtime.upload_bucket,
            "artifact_bucket": runtime.artifact_bucket,
            "max_upload_mb": runtime.max_upload_mb,
            "large_file_mode": runtime.large_file_mode,
            "large_file_max_upload_mb": runtime.large_file_max_upload_mb,
            "active_max_upload_mb": runtime.large_file_max_upload_mb if runtime.large_file_mode else runtime.max_upload_mb,
            "worker_id": runtime.worker_id,
            "worker_stale_after_seconds": runtime.worker_stale_after_seconds,
            "worker_max_attempts": runtime.worker_max_attempts,
        }
    )


@app.post("/api/v1/uploads/init")
def init_upload() -> Any:
    payload = request.get_json(silent=True) or {}
    filename = str(payload.get("filename") or "").strip()
    content_type = str(payload.get("content_type") or "application/octet-stream").strip()
    try:
        size_bytes = int(payload.get("size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise APIError("validation_error", "size_bytes must be an integer.", details={"field": "size_bytes"}) from exc
    try:
        session = _production_store().create_upload_session(filename=filename, size_bytes=size_bytes, content_type=content_type)
    except ProductionStoreError as exc:
        raise _store_error(exc) from exc
    return _response(session, status_code=201)


@app.post("/api/v1/uploads/complete")
def complete_upload() -> Any:
    payload = request.get_json(silent=True) or {}
    try:
        size_bytes = int(payload.get("size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise APIError("validation_error", "size_bytes must be an integer.", details={"field": "size_bytes"}) from exc
    try:
        upload = _production_store().complete_upload(
            upload_id=str(payload.get("upload_id") or "").strip(),
            filename=str(payload.get("filename") or "").strip(),
            storage_path=str(payload.get("storage_path") or "").strip(),
            size_bytes=size_bytes,
            content_type=str(payload.get("content_type") or "application/octet-stream").strip(),
        )
    except ProductionStoreError as exc:
        raise _store_error(exc) from exc
    return _response(upload)


@app.post("/api/v1/uploads")
def create_upload() -> Any:
    uploaded = request.files.get("file")
    if uploaded is None:
        raise APIError("validation_error", "file is required.", details={"field": "file"})
    content = uploaded.read()
    try:
        upload = _production_store().save_upload(
            filename=uploaded.filename or "",
            content=content,
            content_type=uploaded.content_type,
        )
    except ProductionStoreError as exc:
        raise _store_error(exc) from exc
    return _response(upload, status_code=201)


@app.post("/api/v1/runs")
def create_run() -> Any:
    parsed = _parse_run_payload()
    if parsed["mode"] == "uploaded":
        try:
            run = _production_store().create_run(
                upload_id=parsed["upload_id"],
                filename=parsed["filename"],
                upload_storage_path=parsed["upload_storage_path"],
                required_columns=parsed["required_columns"],
                target_crs=parsed["target_crs"],
                size_bytes=parsed.get("size_bytes"),
                content_type=parsed.get("content_type"),
                customer_intake=parsed.get("customer_intake"),
            )
        except ProductionStoreError as exc:
            raise _store_error(exc) from exc
        return _response(
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "submitted_at": run["submitted_at"],
                "filename": run.get("filename"),
            },
            status_code=202,
        )

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    state = RunState(
        run_id=run_id,
        status="queued",
        submitted_at=_utc_now(),
        input_path=parsed["input_path"],
        required_columns=parsed["required_columns"],
        target_crs=parsed["target_crs"],
        customer_intake=parsed.get("customer_intake") or {},
    )
    _write_state(state)
    _launch_run_async(run_id)
    return _response(
        {
            "run_id": run_id,
            "status": state.status,
            "submitted_at": state.submitted_at,
        },
        status_code=202,
    )


@app.get("/api/v1/runs")
def list_runs() -> Any:
    try:
        runs = _production_store().list_runs(limit=int(request.args.get("limit", "20")))
    except ProductionStoreError as exc:
        raise _store_error(exc) from exc
    return _response({"runs": runs})


@app.get("/api/v1/runs/<run_id>")
def get_run(run_id: str) -> Any:
    state = _read_state_or_none(run_id)
    if state is not None:
        payload = state.to_dict()
        if state.run_output_dir:
            payload["review_status"] = read_agent_review_status(state.run_output_dir)
            payload = _enrich_run_payload_with_artifacts(payload)
        return _response(payload)
    try:
        payload = _production_store().get_run(run_id)
        return _response(_enrich_run_payload_with_artifacts(payload))
    except ProductionStoreError as exc:
        raise _store_error(exc, status_code=404) from exc


@app.post("/api/v1/runs/<run_id>/review")
def review_run(run_id: str) -> Any:
    state = _read_state_or_none(run_id)
    if state is None:
        try:
            run = _production_store().get_run(run_id)
        except ProductionStoreError as exc:
            raise _store_error(exc, status_code=404) from exc
        output_dir = run.get("run_output_dir")
        if run.get("status") != "completed" or not output_dir:
            raise APIError("run_not_reviewable", "Run is not ready for review.", status_code=409)
    else:
        if state.status != "completed" or not state.run_output_dir:
            raise APIError("run_not_reviewable", "Run is not ready for review.", status_code=409)
        output_dir = state.run_output_dir

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    reviewer_name = str(payload.get("reviewer_name") or "").strip()
    notes = payload.get("notes")

    if action not in {"approve", "reject"}:
        raise APIError("validation_error", "action must be approve or reject.", details={"field": "action"})
    if not reviewer_name:
        raise APIError("validation_error", "reviewer_name is required.", details={"field": "reviewer_name"})

    try:
        artifacts = review_existing_agent_report(
            str(output_dir),
            action=action,
            reviewer_name=reviewer_name,
            notes=str(notes) if notes is not None else None,
        )
    except Exception as exc:
        raise APIError("review_failed", str(exc), status_code=409) from exc

    review_status = read_agent_review_status(str(output_dir))
    if state is None:
        try:
            _production_store().update_run(run_id, review_status=review_status)
        except ProductionStoreError:
            pass
    return _response(
        {
            "run_id": run_id,
            "action": action,
            "review_status": review_status,
            "artifacts": artifacts,
        }
    )


@app.get("/api/v1/runs/<run_id>/artifacts")
def get_artifacts(run_id: str) -> Any:
    state = _read_state_or_none(run_id)
    if state is not None:
        if state.status != "completed" or not state.run_output_dir:
            raise APIError("artifacts_not_ready", "Artifacts are not available until the run completes.", status_code=409)
        output_dir = Path(state.run_output_dir)
        return _response(
            {
                "run_id": run_id,
                "status": state.status,
                "output_dir": str(output_dir),
                "artifacts": _artifact_manifest(output_dir, run_id=run_id),
            }
        )
    try:
        run = _production_store().get_run(run_id)
    except ProductionStoreError as exc:
        raise _store_error(exc, status_code=404) from exc
    if run.get("status") != "completed":
        raise APIError("artifacts_not_ready", "Artifacts are not available until the run completes.", status_code=409)
    return _response(
        {
            "run_id": run_id,
            "status": run.get("status"),
            "artifacts": run.get("artifacts") or {},
        }
    )


@app.get("/api/v1/runs/<run_id>/artifacts/<artifact_name>/download")
def download_artifact(run_id: str, artifact_name: str) -> Any:
    state = _read_state_or_none(run_id)
    if state is not None:
        if state.status != "completed" or not state.run_output_dir:
            raise APIError("artifacts_not_ready", "Artifacts are not available until the run completes.", status_code=409)
        artifact = _artifact_manifest(Path(state.run_output_dir)).get(artifact_name)
        if not artifact or not artifact["exists"]:
            raise APIError("artifact_not_found", f"Artifact '{artifact_name}' was not found.", status_code=404)
        data = Path(str(artifact["path"])).read_bytes()
        filename = Path(str(artifact["path"])).name
        return Response(data, mimetype="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={filename}"})
    try:
        store = _production_store()
        run = store.get_run(run_id)
        data, filename, content_type = store.artifact_bytes(run, artifact_name)
    except ProductionStoreError as exc:
        raise _store_error(exc, status_code=404) from exc
    return Response(data, mimetype=content_type, headers={"Content-Disposition": f"attachment; filename={filename}"})


# Vercel Python runtime expects a WSGI callable named `app`.
