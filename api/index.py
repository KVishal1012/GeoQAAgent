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
    return Path(os.getenv("GEOQA_OUTPUT_ROOT", "outputs")).resolve()


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
    storage_status = "Supabase configured" if config.supabase_url and config.supabase_service_role_key else "Local fallback"
    api_status = "Protected" if has_api_key else "Open for setup"
    openai_status = "Configured" if has_openai_key else "Not configured"
    max_upload = config.large_file_max_upload_mb if config.large_file_mode else config.max_upload_mb
    upload_mode = "Direct Supabase upload" if config.supabase_url and config.supabase_service_role_key else "Local fallback upload"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GeoQA Agent Upload</title>
  <style>
    :root {{
      --ink: #16221c;
      --muted: #627268;
      --line: #d7dfd8;
      --panel: #fffef9;
      --field: #f3f7f0;
      --accent: #226b4f;
      --accent-2: #d87c36;
      --bad: #9d3328;
      --bg: #eef3ea;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 0%, rgba(216,124,54,.16), transparent 30%),
        linear-gradient(180deg, #fbfcf8 0%, var(--bg) 100%);
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 46px; }}
    .hero {{ display: grid; grid-template-columns: 1.15fr .85fr; gap: 20px; align-items: stretch; }}
    .panel {{ background: rgba(255,254,249,.92); border: 1px solid var(--line); border-radius: 14px; padding: 22px; box-shadow: 0 18px 54px rgba(22,34,28,.08); }}
    h1 {{ margin: 0; font-size: clamp(36px, 5.4vw, 72px); line-height: .96; letter-spacing: -.04em; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 20px 0 8px; font-size: 15px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .lead {{ margin: 16px 0 0; font-size: 18px; max-width: 780px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 18px; }}
    .status-grid {{ display: grid; gap: 10px; }}
    .status {{ display: flex; justify-content: space-between; gap: 12px; padding: 11px 12px; border-radius: 10px; background: var(--field); border: 1px solid var(--line); }}
    .label {{ color: var(--muted); }}
    .value {{ color: var(--accent); font-weight: 750; text-align: right; }}
    label {{ display: block; color: var(--ink); font-weight: 720; margin: 13px 0 7px; }}
    input, button {{ font: inherit; }}
    input[type="text"], input[type="password"] {{ width: 100%; border: 1px solid var(--line); border-radius: 10px; padding: 11px 12px; background: white; color: var(--ink); }}
    input[type="file"] {{ width: 100%; border: 1px dashed var(--accent); border-radius: 12px; padding: 18px; background: #f8fbf4; }}
    button {{ border: 0; border-radius: 11px; padding: 12px 15px; background: var(--accent); color: white; font-weight: 800; cursor: pointer; }}
    button.secondary {{ background: #dfeae2; color: var(--accent); }}
    button:disabled {{ opacity: .55; cursor: not-allowed; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
    .message {{ min-height: 24px; margin-top: 12px; font-weight: 700; color: var(--accent); }}
    .message.error {{ color: var(--bad); }}
    .artifacts a {{ display: inline-block; margin: 6px 8px 0 0; padding: 8px 10px; background: #e7efe7; color: var(--accent); text-decoration: none; border-radius: 9px; font-weight: 700; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; padding: 14px; border-radius: 10px; background: #14221b; color: #ecf5ec; max-height: 320px; overflow: auto; }}
    .small {{ font-size: 13px; }}
    @media (max-width: 860px) {{ .hero, .grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 42px; }} }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="panel">
        <h1>GeoQA Agent</h1>
        <p class="lead">Dataset readiness QA for geospatial teams. Upload a geospatial dataset, queue a deterministic readiness check, and download an evidence-backed QA package.</p>
        <div class="grid">
          <div>
            <h3>Accepted inputs</h3>
            <p class="small">GeoJSON, GeoPackage, or zipped shapefile. Max upload: {max_upload} MB.</p>
            <p class="small">Upload mode: {upload_mode}.</p>
          </div>
          <div>
            <h3>Production flow</h3>
            <p class="small">Vercel handles upload/status through <code>POST /api/v1/runs</code>. A Python worker processes queued GIS jobs.</p>
          </div>
        </div>
      </div>
      <aside class="panel">
        <h2>Deployment Status</h2>
        <div class="status-grid">
          <div class="status"><span class="label">API</span><span class="value">Online</span></div>
          <div class="status"><span class="label">API key</span><span class="value">{api_status}</span></div>
          <div class="status"><span class="label">Storage</span><span class="value">{storage_status}</span></div>
          <div class="status"><span class="label">OpenAI</span><span class="value">{openai_status}</span></div>
          <div class="status"><span class="label">Model</span><span class="value">{llm_model}</span></div>
        </div>
      </aside>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Upload Dataset</h2>
        <label for="apiKey">API key, if configured</label>
        <input id="apiKey" type="password" placeholder="Paste x-api-key for protected deployments" />
        <label for="dataset">Dataset file</label>
        <input id="dataset" type="file" accept=".geojson,.gpkg,.zip,application/zip" />
        <label for="requiredColumns">Required columns, optional</label>
        <input id="requiredColumns" type="text" placeholder="asset_id, road_name" />
        <label for="targetCrs">Target CRS / SRID for optional reprojection</label>
        <input id="targetCrs" type="text" list="crsPresets" placeholder="Keep source CRS, or enter EPSG:4326 / 3857" />
        <datalist id="crsPresets">
          <option value="EPSG:4326">WGS 84 longitude/latitude</option>
          <option value="EPSG:3857">Web Mercator</option>
          <option value="4326">SRID 4326</option>
          <option value="3857">SRID 3857</option>
        </datalist>
        <p class="small">Leave blank to keep the source CRS. Enter an EPSG code only when the source CRS is known.</p>
        <div class="actions">
          <button id="submitRun">Upload and queue QA</button>
          <button id="refreshRun" class="secondary" disabled>Refresh status</button>
        </div>
        <div id="message" class="message"></div>
      </div>
      <div class="panel">
        <h2>Run Status</h2>
        <div class="status-grid">
          <div class="status"><span class="label">Run ID</span><span id="runId" class="value">Not started</span></div>
          <div class="status"><span class="label">Status</span><span id="runStatus" class="value">Waiting</span></div>
          <div class="status"><span class="label">Readiness</span><span id="readiness" class="value">-</span></div>
          <div class="status"><span class="label">Issues</span><span id="issues" class="value">-</span></div>
        </div>
        <h3>Downloads</h3>
        <div id="artifacts" class="artifacts"><p class="small">Artifacts appear after the worker completes the run.</p></div>
        <h3>Recent Runs</h3>
        <div id="recentRuns"><p class="small">Recent production runs load after page startup.</p></div>
      </div>
    </section>

    <section class="panel" style="margin-top: 16px;">
      <h2>Raw Run Response</h2>
      <pre id="raw">{{}}</pre>
    </section>
  </main>
  <script>
    let currentRunId = null;
    let pollTimer = null;
    const $ = (id) => document.getElementById(id);
    function headers(json = false) {{
      const value = $("apiKey").value.trim();
      const output = {{}};
      if (value) output["x-api-key"] = value;
      if (json) output["Content-Type"] = "application/json";
      return output;
    }}
    function setMessage(text, isError = false) {{
      $("message").textContent = text;
      $("message").className = "message" + (isError ? " error" : "");
    }}
    async function readJson(response) {{
      const payload = await response.json();
      if (!response.ok) {{
        const error = payload.error || {{}};
        throw new Error(error.message || "Request failed");
      }}
      return payload;
    }}
    function renderRun(payload) {{
      $("raw").textContent = JSON.stringify(payload, null, 2);
      $("runId").textContent = payload.run_id || currentRunId || "Not started";
      $("runStatus").textContent = payload.status || "unknown";
      const band = payload.readiness_band || "-";
      const score = payload.readiness_score ?? "-";
      $("readiness").textContent = band === "-" ? "-" : `${{band}} (${{score}})`;
      const counts = payload.issue_counts || {{}};
      $("issues").textContent = counts.total ?? "-";
    }}
    async function loadArtifacts(runId) {{
      const response = await fetch(`/api/v1/runs/${{runId}}/artifacts`, {{ headers: headers() }});
      if (!response.ok) return;
      const payload = await response.json();
      const links = [];
      for (const [name, artifact] of Object.entries(payload.artifacts || {{}})) {{
        if (artifact.exists && artifact.url) {{
          links.push(`<a href="${{artifact.url}}" target="_blank" rel="noopener">${{name}}</a>`);
        }}
      }}
      $("artifacts").innerHTML = links.length ? links.join("") : "<p class='small'>No downloadable artifacts yet.</p>";
    }}
    async function loadRecentRuns() {{
      const response = await fetch("/api/v1/runs?limit=5", {{ headers: headers() }});
      if (!response.ok) return;
      const payload = await response.json();
      const rows = payload.runs || [];
      if (!rows.length) {{
        $("recentRuns").innerHTML = "<p class='small'>No production runs yet.</p>";
        return;
      }}
      $("recentRuns").innerHTML = rows.map((run) => `<p class="small"><strong>${{run.filename || run.run_id}}</strong><br>${{run.status}} · ${{run.readiness_band || "pending"}} · <button class="secondary" onclick="openRun('${{run.run_id}}')">Open</button></p>`).join("");
    }}
    async function openRun(runId) {{
      currentRunId = runId;
      $("refreshRun").disabled = false;
      await refreshRun();
    }}
    async function uploadDatasetFile(file) {{
      const initResponse = await fetch("/api/v1/uploads/init", {{
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({{ filename: file.name, size_bytes: file.size, content_type: file.type || "application/octet-stream" }})
      }});
      const session = await readJson(initResponse);
      if (!session.direct_upload) {{
        const form = new FormData();
        form.append("file", file);
        const uploadResponse = await fetch(session.fallback_upload_url || "/api/v1/uploads", {{ method: "POST", headers: headers(), body: form }});
        return await readJson(uploadResponse);
      }}
      setMessage("Uploading directly to Supabase Storage...");
      const uploadHeaders = session.upload_headers || {{}};
      const uploadResponse = await fetch(session.upload_url, {{ method: session.upload_method || "PUT", headers: uploadHeaders, body: file }});
      if (!uploadResponse.ok) throw new Error("Direct storage upload failed.");
      const completeResponse = await fetch("/api/v1/uploads/complete", {{
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({{
          upload_id: session.upload_id,
          filename: session.filename,
          storage_path: session.storage_path,
          size_bytes: file.size,
          content_type: file.type || "application/octet-stream"
        }})
      }});
      return await readJson(completeResponse);
    }}
    async function refreshRun() {{
      if (!currentRunId) return;
      const response = await fetch(`/api/v1/runs/${{currentRunId}}`, {{ headers: headers() }});
      const payload = await readJson(response);
      renderRun(payload);
      if (payload.status === "completed") {{
        clearInterval(pollTimer);
        await loadArtifacts(currentRunId);
        setMessage("Run completed. Downloads are ready.");
      }} else if (payload.status === "failed") {{
        clearInterval(pollTimer);
        setMessage(payload.error || "Run failed.", true);
      }} else {{
        setMessage("Run is queued or running. Keep this page open.");
      }}
    }}
    $("refreshRun").addEventListener("click", refreshRun);
    $("submitRun").addEventListener("click", async () => {{
      try {{
        const file = $("dataset").files[0];
        if (!file) throw new Error("Choose a dataset file first.");
        $("submitRun").disabled = true;
        setMessage("Preparing upload...");
        const upload = await uploadDatasetFile(file);
        setMessage("Upload complete. Queueing QA run...");
        const requiredColumns = $("requiredColumns").value.split(",").map((value) => value.trim()).filter(Boolean);
        const targetCrs = $("targetCrs").value.trim() || null;
        const runResponse = await fetch("/api/v1/runs", {{
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({{
            upload_id: upload.upload_id,
            upload_storage_path: upload.storage_path,
            filename: upload.filename,
            required_columns: requiredColumns,
            target_crs: targetCrs,
            target_srid: targetCrs
          }})
        }});
        const run = await readJson(runResponse);
        currentRunId = run.run_id;
        $("refreshRun").disabled = false;
        renderRun(run);
        setMessage("Run queued. Worker will process it asynchronously.");
        await loadRecentRuns();
        clearInterval(pollTimer);
        pollTimer = setInterval(refreshRun, 3000);
      }} catch (error) {{
        setMessage(error.message, true);
      }} finally {{
        $("submitRun").disabled = false;
      }}
    }});
    loadRecentRuns();
  </script>
</body>
</html>"""


def _artifact_manifest(output_dir: Path, run_id: str | None = None) -> dict[str, Any]:
    artifact_map = {
        "qa_report": output_dir / "qa_report.md",
        "issues_csv": output_dir / "issues.csv",
        "run_record": output_dir / "run_record.json",
        "summary": output_dir / "summary.json",
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
        return _response(payload)
    try:
        return _response(_production_store().get_run(run_id))
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
