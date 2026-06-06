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

from geoqa.reporting.agent_report_generator import read_agent_review_status, review_existing_agent_report
from geoqa.runner import run_geoqa

app = Flask(__name__)

_STATE_LOCK = threading.Lock()


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


def _output_root() -> Path:
    return Path(os.getenv("GEOQA_OUTPUT_ROOT", "outputs")).resolve()


def _state_root() -> Path:
    root = _output_root() / "api_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run_state_path(run_id: str) -> Path:
    return _state_root() / f"{run_id}.json"


def _write_state(state: RunState) -> None:
    with _STATE_LOCK:
        _run_state_path(state.run_id).write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def _read_state(run_id: str) -> RunState:
    path = _run_state_path(run_id)
    if not path.exists():
        raise APIError("run_not_found", f"Run '{run_id}' was not found.", status_code=404)
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


def _parse_run_payload() -> tuple[str, list[str], str | None]:
    payload = request.get_json(silent=True) or {}
    input_path = str(payload.get("input_path") or "").strip()
    if not input_path:
        raise APIError("validation_error", "input_path is required.", details={"field": "input_path"})
    if not Path(input_path).exists():
        raise APIError("input_not_found", f"input_path does not exist: {input_path}", status_code=404)

    raw_columns = payload.get("required_columns") or []
    if not isinstance(raw_columns, list):
        raise APIError("validation_error", "required_columns must be a list of strings.", details={"field": "required_columns"})
    required_columns = [str(value).strip() for value in raw_columns if str(value).strip()]

    target_crs_value = payload.get("target_crs")
    target_crs = str(target_crs_value).strip() if target_crs_value is not None else None
    if target_crs == "":
        target_crs = None

    return input_path, required_columns, target_crs


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


def _landing_page_html() -> str:
    has_api_key = bool(os.getenv("GEOQA_API_KEY"))
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    llm_model = os.getenv("GEOQA_LLM_MODEL") or "not configured"
    output_root = str(_output_root())
    api_status = "Protected" if has_api_key else "Open for setup"
    openai_status = "Configured" if has_openai_key else "Not configured"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GeoQA Agent</title>
  <style>
    :root {{
      --ink: #17201b;
      --muted: #5d6b63;
      --line: #d8dfd8;
      --panel: #ffffff;
      --field: #f4f7f2;
      --accent: #1f7a5a;
      --accent-ink: #0d3d2d;
      --warn: #9a5b13;
      --bg: #eef3ec;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        linear-gradient(135deg, rgba(31,122,90,.10), transparent 34%),
        linear-gradient(180deg, #fbfcf9 0%, var(--bg) 100%);
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }}
    .mast {{ display: grid; grid-template-columns: 1.5fr .9fr; gap: 28px; align-items: stretch; }}
    h1 {{ margin: 0; font-size: clamp(34px, 5vw, 68px); line-height: 1; letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    p {{ margin: 0; color: var(--muted); line-height: 1.6; }}
    .lead {{ margin-top: 18px; font-size: 18px; max-width: 760px; }}
    .panel {{ background: rgba(255,255,255,.86); border: 1px solid var(--line); border-radius: 8px; padding: 22px; box-shadow: 0 18px 60px rgba(23,32,27,.08); }}
    .status-grid {{ display: grid; gap: 12px; margin-top: 18px; }}
    .status {{ display: flex; justify-content: space-between; gap: 16px; border: 1px solid var(--line); background: var(--field); padding: 12px 14px; border-radius: 6px; }}
    .label {{ color: var(--muted); }}
    .value {{ color: var(--accent-ink); font-weight: 700; text-align: right; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }}
    a.button {{ color: white; background: var(--accent); text-decoration: none; padding: 11px 14px; border-radius: 6px; font-weight: 700; }}
    a.button.secondary {{ color: var(--accent-ink); background: #dcebe4; }}
    .sections {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 26px; }}
    .step {{ border-top: 3px solid var(--accent); }}
    code {{ display: inline-block; max-width: 100%; overflow-wrap: anywhere; color: var(--accent-ink); background: #e8efe8; border: 1px solid var(--line); border-radius: 4px; padding: 2px 5px; }}
    ul {{ margin: 12px 0 0; padding-left: 18px; color: var(--muted); line-height: 1.7; }}
    .note {{ margin-top: 24px; color: var(--warn); }}
    @media (max-width: 820px) {{
      main {{ padding: 28px 0; }}
      .mast, .sections {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 42px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="mast">
      <div class="panel">
        <h1>GeoQA Agent</h1>
        <p class="lead">Dataset readiness QA for geospatial teams. Run deterministic checks, keep evidence artifacts, and use a grounded agent workflow for review-ready handoffs.</p>
        <div class="actions">
          <a class="button" href="/health">Health</a>
          <a class="button secondary" href="/config">Config</a>
        </div>
      </div>
      <aside class="panel">
        <h2>Deployment Status</h2>
        <div class="status-grid">
          <div class="status"><span class="label">API</span><span class="value">Online</span></div>
          <div class="status"><span class="label">API key</span><span class="value">{api_status}</span></div>
          <div class="status"><span class="label">OpenAI</span><span class="value">{openai_status}</span></div>
          <div class="status"><span class="label">Model</span><span class="value">{llm_model}</span></div>
        </div>
      </aside>
    </section>

    <section class="sections">
      <div class="panel step">
        <h2>1. Submit A Run</h2>
        <p>Use <code>POST /api/v1/runs</code> to queue a dataset readiness check.</p>
      </div>
      <div class="panel step">
        <h2>2. Review Evidence</h2>
        <p>Poll <code>GET /api/v1/runs/&lt;id&gt;</code> and inspect generated QA artifacts.</p>
      </div>
      <div class="panel step">
        <h2>3. Handoff</h2>
        <p>Use artifact metadata and review state to support downstream team handoff.</p>
      </div>
    </section>

    <section class="panel" style="margin-top: 18px;">
      <h2>Available API Routes</h2>
      <ul>
        <li><code>GET /health</code></li>
        <li><code>GET /config</code></li>
        <li><code>POST /api/v1/runs</code></li>
        <li><code>GET /api/v1/runs/&lt;run_id&gt;</code></li>
        <li><code>POST /api/v1/runs/&lt;run_id&gt;/review</code></li>
        <li><code>GET /api/v1/runs/&lt;run_id&gt;/artifacts</code></li>
      </ul>
      <p class="note">Output root: <code>{output_root}</code>. For full analyst UI workflows, run the Streamlit console on a stateful host.</p>
    </section>
  </main>
</body>
</html>"""


def _artifact_manifest(output_dir: Path) -> dict[str, Any]:
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
        artifacts[name] = {
            "path": str(path),
            "exists": path.exists(),
            "url": None,
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
    return _response(
        {
            "agent_report_enabled": os.getenv("GEOQA_AGENT_REPORT_ENABLED", "true"),
            "has_openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
            "llm_model": os.getenv("GEOQA_LLM_MODEL"),
            "output_root": str(_output_root()),
            "has_api_key": bool(os.getenv("GEOQA_API_KEY")),
        }
    )


@app.post("/api/v1/runs")
def create_run() -> Any:
    input_path, required_columns, target_crs = _parse_run_payload()
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    state = RunState(
        run_id=run_id,
        status="queued",
        submitted_at=_utc_now(),
        input_path=input_path,
        required_columns=required_columns,
        target_crs=target_crs,
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


@app.get("/api/v1/runs/<run_id>")
def get_run(run_id: str) -> Any:
    state = _read_state(run_id)
    payload = state.to_dict()
    if state.run_output_dir:
        payload["review_status"] = read_agent_review_status(state.run_output_dir)
    return _response(payload)


@app.post("/api/v1/runs/<run_id>/review")
def review_run(run_id: str) -> Any:
    state = _read_state(run_id)
    if state.status != "completed" or not state.run_output_dir:
        raise APIError("run_not_reviewable", "Run is not ready for review.", status_code=409)

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
            state.run_output_dir,
            action=action,
            reviewer_name=reviewer_name,
            notes=str(notes) if notes is not None else None,
        )
    except Exception as exc:
        raise APIError("review_failed", str(exc), status_code=409) from exc

    review_status = read_agent_review_status(state.run_output_dir)
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
    state = _read_state(run_id)
    if state.status != "completed" or not state.run_output_dir:
        raise APIError("artifacts_not_ready", "Artifacts are not available until the run completes.", status_code=409)

    output_dir = Path(state.run_output_dir)
    return _response(
        {
            "run_id": run_id,
            "status": state.status,
            "output_dir": str(output_dir),
            "artifacts": _artifact_manifest(output_dir),
        }
    )


# Vercel Python runtime expects a WSGI callable named `app`.
