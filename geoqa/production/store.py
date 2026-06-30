from __future__ import annotations

import errno
import json
import mimetypes
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from geoqa.config import AppConfig, load_app_config

ALLOWED_UPLOAD_EXTENSIONS = {".geojson", ".gpkg", ".zip"}
RESUMABLE_UPLOAD_THRESHOLD_BYTES = 6 * 1024 * 1024
RESUMABLE_UPLOAD_CHUNK_BYTES = 6 * 1024 * 1024
SUPABASE_REQUEST_MAX_ATTEMPTS = 3
SUPABASE_REQUEST_RETRY_SECONDS = 0.5
TRANSIENT_URL_ERROR_ERRNOS = {
    errno.EBUSY,
    errno.ECONNRESET,
    errno.ECONNREFUSED,
    errno.EHOSTUNREACH,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
}
TRANSIENT_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
ARTIFACT_NAMES = {
    "qa_report": "qa_report.md",
    "issues_csv": "issues.csv",
    "summary": "summary.json",
    "run_record": "run_record.json",
    "geometry_profile": "geometry_profile.json",
    "customer_report": "customer_report.md",
    "customer_report_pdf": "customer_report.pdf",
    "customer_intake": "customer_intake.json",
    "handoff_bundle": "handoff_bundle.zip",
    "agent_report_draft": "agent_report_draft.md",
    "agent_report": "agent_report.md",
    "review_status": "review_status.json",
}


class ProductionStoreError(RuntimeError):
    """Raised when production upload/run state cannot be persisted."""


@dataclass(frozen=True, slots=True)
class UploadValidation:
    filename: str
    extension: str
    size_bytes: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def active_upload_limit_mb(config: AppConfig) -> int:
    if config.large_file_mode:
        if not (config.supabase_url and config.supabase_service_role_key):
            raise ProductionStoreError("Large-file mode requires Supabase storage. Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
        return config.large_file_max_upload_mb
    return config.max_upload_mb


def validate_upload(filename: str, size_bytes: int, max_upload_mb: int) -> UploadValidation:
    clean_name = Path(filename or "").name
    extension = Path(clean_name).suffix.lower()
    if not clean_name:
        raise ProductionStoreError("A filename is required.")
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise ProductionStoreError(f"Unsupported file type. Upload one of: {allowed}.")
    max_bytes = max_upload_mb * 1024 * 1024
    if size_bytes <= 0:
        raise ProductionStoreError("Uploaded file is empty.")
    if size_bytes > max_bytes:
        raise ProductionStoreError(f"Uploaded file exceeds the {max_upload_mb} MB limit.")
    return UploadValidation(filename=clean_name, extension=extension, size_bytes=size_bytes)


def build_production_store(config: AppConfig | None = None) -> "BaseProductionStore":
    config = config or load_app_config()
    if config.supabase_url and config.supabase_service_role_key:
        return SupabaseProductionStore(config)
    return LocalProductionStore(config)


class BaseProductionStore:
    def create_upload_session(self, *, filename: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def complete_upload(self, *, upload_id: str, filename: str, storage_path: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def save_upload(self, *, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def create_run(
        self,
        *,
        upload_id: str,
        filename: str,
        upload_storage_path: str,
        required_columns: list[str] | None = None,
        target_crs: str | None = None,
        size_bytes: int | None = None,
        content_type: str | None = None,
        customer_intake: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def claim_next_run(self, *, worker_id: str, stale_after_seconds: int, max_attempts: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def heartbeat_run(self, run_id: str, *, worker_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_run(self, run_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any]:
        raise NotImplementedError

    def append_event(self, run_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_queued_runs(self, limit: int = 1) -> list[dict[str, Any]]:
        raise NotImplementedError

    def download_upload(self, run: dict[str, Any], destination_dir: str | Path) -> Path:
        raise NotImplementedError

    def upload_artifacts(self, run_id: str, output_dir: str | Path) -> dict[str, Any]:
        raise NotImplementedError

    def artifact_bytes(self, run: dict[str, Any], artifact_name: str) -> tuple[bytes, str, str]:
        raise NotImplementedError


class LocalProductionStore(BaseProductionStore):
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.root = Path(config.output_root).resolve() / "production_mvp"
        self.uploads_dir = self.root / "uploads"
        self.runs_dir = self.root / "runs"
        self.events_dir = self.root / "events"
        self.artifacts_dir = self.root / "artifacts"
        for path in (self.uploads_dir, self.runs_dir, self.events_dir, self.artifacts_dir):
            path.mkdir(parents=True, exist_ok=True)

    def create_upload_session(self, *, filename: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, size_bytes, active_upload_limit_mb(self.config))
        upload_id = f"upload-{uuid.uuid4().hex[:12]}"
        storage_path = str(self.uploads_dir / f"{upload_id}{validation.extension}")
        return {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": content_type or mimetypes.guess_type(validation.filename)[0] or "application/octet-stream",
            "size_bytes": validation.size_bytes,
            "storage_provider": "local",
            "storage_path": storage_path,
            "direct_upload": False,
            "fallback_upload_url": "/api/v1/uploads",
            "max_upload_mb": active_upload_limit_mb(self.config),
        }

    def complete_upload(self, *, upload_id: str, filename: str, storage_path: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, size_bytes, active_upload_limit_mb(self.config))
        return {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": content_type or mimetypes.guess_type(validation.filename)[0] or "application/octet-stream",
            "size_bytes": validation.size_bytes,
            "storage_provider": "local",
            "storage_path": storage_path,
            "upload_completed_at": utc_now(),
        }

    def save_upload(self, *, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, len(content), self.config.max_upload_mb)
        upload_id = f"upload-{uuid.uuid4().hex[:12]}"
        storage_name = f"{upload_id}{validation.extension}"
        storage_path = self.uploads_dir / storage_name
        storage_path.write_bytes(content)
        return {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": content_type or mimetypes.guess_type(validation.filename)[0] or "application/octet-stream",
            "size_bytes": validation.size_bytes,
            "storage_provider": "local",
            "storage_path": str(storage_path),
            "upload_completed_at": utc_now(),
            "created_at": utc_now(),
        }

    def create_run(
        self,
        *,
        upload_id: str,
        filename: str,
        upload_storage_path: str,
        required_columns: list[str] | None = None,
        target_crs: str | None = None,
        size_bytes: int | None = None,
        content_type: str | None = None,
        customer_intake: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        run = {
            "run_id": run_id,
            "status": "queued",
            "submitted_at": now,
            "updated_at": now,
            "filename": filename,
            "upload_id": upload_id,
            "upload_storage_path": upload_storage_path,
            "required_columns": required_columns or [],
            "target_crs": target_crs,
            "size_bytes": size_bytes,
            "content_type": content_type,
            "customer_intake": customer_intake or {},
            "upload_completed_at": now,
            "readiness_score": None,
            "readiness_band": None,
            "issue_counts": None,
            "review_status": None,
            "run_output_dir": None,
            "artifacts": {},
            "error": None,
            "error_type": None,
            "claimed_at": None,
            "claimed_by": None,
            "last_heartbeat_at": None,
            "attempt_count": 0,
            "max_attempts": self.config.worker_max_attempts,
        }
        self._write_run(run)
        self.append_event(run_id, "queued", {"filename": filename})
        return run

    def claim_next_run(self, *, worker_id: str, stale_after_seconds: int, max_attempts: int) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        candidates = []
        for run in self.list_runs(limit=1000):
            attempts = int(run.get("attempt_count") or 0)
            max_for_run = int(run.get("max_attempts") or max_attempts)
            if attempts >= max_for_run:
                continue
            if run.get("status") == "queued":
                candidates.append(run)
                continue
            if run.get("status") == "running":
                heartbeat = _parse_time(run.get("last_heartbeat_at") or run.get("claimed_at"))
                if heartbeat and now - heartbeat > timedelta(seconds=stale_after_seconds):
                    candidates.append(run)
        candidates.sort(key=lambda row: str(row.get("submitted_at") or ""))
        if not candidates:
            return None
        run = candidates[0]
        next_attempt = int(run.get("attempt_count") or 0) + 1
        return self.update_run(
            str(run["run_id"]),
            status="running",
            claimed_at=utc_now(),
            claimed_by=worker_id,
            last_heartbeat_at=utc_now(),
            attempt_count=next_attempt,
            max_attempts=int(run.get("max_attempts") or max_attempts),
            error=None,
            error_type=None,
        )

    def heartbeat_run(self, run_id: str, *, worker_id: str) -> dict[str, Any]:
        return self.update_run(run_id, last_heartbeat_at=utc_now(), claimed_by=worker_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        path = self._run_path(run_id)
        if not path.exists():
            raise ProductionStoreError(f"Run '{run_id}' was not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any]:
        run = self.get_run(run_id)
        run.update(updates)
        run["updated_at"] = utc_now()
        self._write_run(run)
        if "status" in updates:
            self.append_event(run_id, str(updates["status"]), {k: v for k, v in updates.items() if k != "status"})
        return run

    def append_event(self, run_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        path = self.events_dir / f"{run_id}.jsonl"
        event = {"run_id": run_id, "event_type": event_type, "timestamp": utc_now(), "details": details or {}}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = [json.loads(path.read_text(encoding="utf-8")) for path in self.runs_dir.glob("run-*.json")]
        rows.sort(key=lambda row: str(row.get("submitted_at") or ""), reverse=True)
        return rows[:limit]

    def list_queued_runs(self, limit: int = 1) -> list[dict[str, Any]]:
        rows = [row for row in self.list_runs(limit=1000) if row.get("status") == "queued"]
        rows.sort(key=lambda row: str(row.get("submitted_at") or ""))
        return rows[:limit]

    def download_upload(self, run: dict[str, Any], destination_dir: str | Path) -> Path:
        source = Path(str(run["upload_storage_path"]))
        destination = Path(destination_dir) / Path(str(run["filename"])).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    def upload_artifacts(self, run_id: str, output_dir: str | Path) -> dict[str, Any]:
        output_path = Path(output_dir)
        run_artifact_dir = self.artifacts_dir / run_id
        run_artifact_dir.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, Any] = {}
        for key, filename in ARTIFACT_NAMES.items():
            source = output_path / filename
            exists = source.exists()
            target = run_artifact_dir / filename
            if exists:
                shutil.copy2(source, target)
            artifacts[key] = {
                "filename": filename,
                "exists": exists,
                "storage_provider": "local",
                "storage_path": str(target),
                "url": f"/api/v1/runs/{run_id}/artifacts/{key}/download" if exists else None,
            }
        return artifacts

    def artifact_bytes(self, run: dict[str, Any], artifact_name: str) -> tuple[bytes, str, str]:
        artifacts = run.get("artifacts") or {}
        artifact = artifacts.get(artifact_name)
        if not artifact or not artifact.get("exists"):
            raise ProductionStoreError(f"Artifact '{artifact_name}' is not available.")
        path = Path(str(artifact["storage_path"]))
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.read_bytes(), path.name, content_type

    def _run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _write_run(self, run: dict[str, Any]) -> None:
        self._run_path(str(run["run_id"])).write_text(json.dumps(run, indent=2), encoding="utf-8")


class SupabaseProductionStore(BaseProductionStore):
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.base_url = str(config.supabase_url).rstrip("/")
        self.service_key = str(config.supabase_service_role_key)

    def create_upload_session(self, *, filename: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, size_bytes, active_upload_limit_mb(self.config))
        upload_id = f"upload-{uuid.uuid4().hex[:12]}"
        object_path = f"{upload_id}/{validation.filename}"
        resolved_content_type = content_type or mimetypes.guess_type(validation.filename)[0] or "application/octet-stream"
        use_resumable = validation.size_bytes > RESUMABLE_UPLOAD_THRESHOLD_BYTES
        signed_url = ""
        token = None
        if not use_resumable:
            signed = self._create_signed_upload_url(self.config.upload_bucket, object_path)
            signed_url = str(signed.get("signedURL") or signed.get("signedUrl") or signed.get("url") or "")
            token = signed.get("token")
            if signed_url.startswith("/"):
                signed_url = f"{self.base_url}/storage/v1{signed_url}"
        elif not self.config.supabase_public_key:
            raise ProductionStoreError(
                "Large resumable uploads require SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY in addition to Supabase storage."
            )

        session = {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": resolved_content_type,
            "size_bytes": validation.size_bytes,
            "storage_provider": "supabase",
            "upload_bucket": self.config.upload_bucket,
            "storage_path": object_path,
            "direct_upload": True,
            "resumable_upload": use_resumable,
            "max_upload_mb": active_upload_limit_mb(self.config),
        }
        if use_resumable:
            storage_host = self.base_url.replace("https://", "https://").replace(".supabase.co", ".storage.supabase.co")
            session.update(
                {
                    "resumable_upload_url": f"{storage_host}/storage/v1/upload/resumable",
                    "resumable_chunk_bytes": RESUMABLE_UPLOAD_CHUNK_BYTES,
                    "resumable_headers": {
                        "Authorization": f"Bearer {self.config.supabase_public_key}",
                        "apikey": self.config.supabase_public_key,
                        "x-upsert": "true",
                    },
                }
            )
        else:
            session.update(
                {
                    "upload_url": signed_url,
                    "upload_token": token,
                    "upload_method": "PUT",
                    "upload_headers": {"Content-Type": resolved_content_type},
                }
            )
        return session

    def complete_upload(self, *, upload_id: str, filename: str, storage_path: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, size_bytes, active_upload_limit_mb(self.config))
        return {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": content_type or mimetypes.guess_type(validation.filename)[0] or "application/octet-stream",
            "size_bytes": validation.size_bytes,
            "storage_provider": "supabase",
            "storage_path": storage_path,
            "upload_completed_at": utc_now(),
        }

    def save_upload(self, *, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
        validation = validate_upload(filename, len(content), self.config.max_upload_mb)
        upload_id = f"upload-{uuid.uuid4().hex[:12]}"
        object_path = f"{upload_id}/{validation.filename}"
        self._storage_put(self.config.upload_bucket, object_path, content, content_type or "application/octet-stream")
        return {
            "upload_id": upload_id,
            "filename": validation.filename,
            "content_type": content_type or "application/octet-stream",
            "size_bytes": validation.size_bytes,
            "storage_provider": "supabase",
            "storage_path": object_path,
            "upload_completed_at": utc_now(),
            "created_at": utc_now(),
        }

    def create_run(
        self,
        *,
        upload_id: str,
        filename: str,
        upload_storage_path: str,
        required_columns: list[str] | None = None,
        target_crs: str | None = None,
        size_bytes: int | None = None,
        content_type: str | None = None,
        customer_intake: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = {
            "run_id": f"run-{uuid.uuid4().hex[:12]}",
            "status": "queued",
            "submitted_at": utc_now(),
            "updated_at": utc_now(),
            "filename": filename,
            "upload_id": upload_id,
            "upload_storage_path": upload_storage_path,
            "required_columns": required_columns or [],
            "target_crs": target_crs,
            "size_bytes": size_bytes,
            "content_type": content_type,
            "customer_intake": customer_intake or {},
            "upload_completed_at": utc_now(),
            "artifacts": {},
            "attempt_count": 0,
            "max_attempts": self.config.worker_max_attempts,
        }
        created = self._rest("POST", "geoqa_runs", run, prefer="return=representation")
        self.append_event(run["run_id"], "queued", {"filename": filename})
        return created[0] if isinstance(created, list) and created else run

    def claim_next_run(self, *, worker_id: str, stale_after_seconds: int, max_attempts: int) -> dict[str, Any] | None:
        candidates = self._claim_candidates(stale_after_seconds=stale_after_seconds, max_attempts=max_attempts)
        for run in candidates:
            run_id = str(run["run_id"])
            attempt_count = int(run.get("attempt_count") or 0) + 1
            updated = self.update_run(
                run_id,
                status="running",
                claimed_at=utc_now(),
                claimed_by=worker_id,
                last_heartbeat_at=utc_now(),
                attempt_count=attempt_count,
                max_attempts=int(run.get("max_attempts") or max_attempts),
                error=None,
                error_type=None,
            )
            return updated
        return None

    def heartbeat_run(self, run_id: str, *, worker_id: str) -> dict[str, Any]:
        return self.update_run(run_id, last_heartbeat_at=utc_now(), claimed_by=worker_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        rows = self._rest("GET", f"geoqa_runs?run_id=eq.{urllib.parse.quote(run_id)}&limit=1")
        if not rows:
            raise ProductionStoreError(f"Run '{run_id}' was not found.")
        return rows[0]

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any]:
        updates["updated_at"] = utc_now()
        rows = self._rest(
            "PATCH",
            f"geoqa_runs?run_id=eq.{urllib.parse.quote(run_id)}",
            updates,
            prefer="return=representation",
        )
        if "status" in updates:
            self.append_event(run_id, str(updates["status"]), {k: v for k, v in updates.items() if k != "status"})
        return rows[0] if isinstance(rows, list) and rows else self.get_run(run_id)

    def append_event(self, run_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        self._rest(
            "POST",
            "geoqa_run_events",
            {"run_id": run_id, "event_type": event_type, "timestamp": utc_now(), "details": details or {}},
        )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._rest("GET", f"geoqa_runs?order=submitted_at.desc&limit={int(limit)}")

    def list_queued_runs(self, limit: int = 1) -> list[dict[str, Any]]:
        return self._rest("GET", f"geoqa_runs?status=eq.queued&order=submitted_at.asc&limit={int(limit)}")

    def download_upload(self, run: dict[str, Any], destination_dir: str | Path) -> Path:
        data = self._storage_get(self.config.upload_bucket, str(run["upload_storage_path"]))
        destination = Path(destination_dir) / Path(str(run["filename"])).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def upload_artifacts(self, run_id: str, output_dir: str | Path) -> dict[str, Any]:
        output_path = Path(output_dir)
        artifacts: dict[str, Any] = {}
        for key, filename in ARTIFACT_NAMES.items():
            source = output_path / filename
            object_path = f"{run_id}/{filename}"
            exists = source.exists()
            if exists:
                self._storage_put(self.config.artifact_bucket, object_path, source.read_bytes(), mimetypes.guess_type(filename)[0])
            artifacts[key] = {
                "filename": filename,
                "exists": exists,
                "storage_provider": "supabase",
                "storage_path": object_path,
                "url": f"/api/v1/runs/{run_id}/artifacts/{key}/download" if exists else None,
            }
        return artifacts

    def artifact_bytes(self, run: dict[str, Any], artifact_name: str) -> tuple[bytes, str, str]:
        artifact = (run.get("artifacts") or {}).get(artifact_name)
        if not artifact or not artifact.get("exists"):
            raise ProductionStoreError(f"Artifact '{artifact_name}' is not available.")
        filename = str(artifact.get("filename") or ARTIFACT_NAMES.get(artifact_name, artifact_name))
        data = self._storage_get(self.config.artifact_bucket, str(artifact["storage_path"]))
        return data, filename, mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def _claim_candidates(self, *, stale_after_seconds: int, max_attempts: int) -> list[dict[str, Any]]:
        queued = self._rest("GET", f"geoqa_runs?status=eq.queued&order=submitted_at.asc&limit=5")
        if queued:
            return [row for row in queued if int(row.get("attempt_count") or 0) < int(row.get("max_attempts") or max_attempts)]
        stale_before = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat()
        stale = self._rest(
            "GET",
            "geoqa_runs?status=eq.running"
            f"&last_heartbeat_at=lt.{urllib.parse.quote(stale_before)}"
            "&order=submitted_at.asc&limit=5",
        )
        return [row for row in stale if int(row.get("attempt_count") or 0) < int(row.get("max_attempts") or max_attempts)]

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": content_type,
        }

    def _rest(self, method: str, path: str, payload: dict[str, Any] | None = None, prefer: str | None = None) -> Any:
        url = f"{self.base_url}/rest/v1/{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._headers()
        if prefer:
            headers["Prefer"] = prefer
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        return self._request_json(request)

    def _create_signed_upload_url(self, bucket: str, object_path: str) -> dict[str, Any]:
        encoded_path = "/".join(urllib.parse.quote(part) for part in object_path.split("/"))
        url = f"{self.base_url}/storage/v1/object/upload/sign/{bucket}/{encoded_path}"
        request = urllib.request.Request(url, data=json.dumps({"upsert": True}).encode("utf-8"), headers=self._headers(), method="POST")
        return self._request_json(request)

    def _storage_put(self, bucket: str, object_path: str, data: bytes, content_type: str | None) -> None:
        encoded_path = "/".join(urllib.parse.quote(part) for part in object_path.split("/"))
        url = f"{self.base_url}/storage/v1/object/{bucket}/{encoded_path}"
        headers = self._headers(content_type or "application/octet-stream")
        headers["x-upsert"] = "true"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        self._request_bytes(request)

    def _storage_get(self, bucket: str, object_path: str) -> bytes:
        encoded_path = "/".join(urllib.parse.quote(part) for part in object_path.split("/"))
        url = f"{self.base_url}/storage/v1/object/{bucket}/{encoded_path}"
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        return self._request_bytes(request)

    def _request_json(self, request: urllib.request.Request) -> Any:
        raw = self._request_bytes(request)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _request_bytes(self, request: urllib.request.Request) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, SUPABASE_REQUEST_MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                if exc.code not in TRANSIENT_HTTP_STATUS_CODES or attempt == SUPABASE_REQUEST_MAX_ATTEMPTS:
                    raise ProductionStoreError(f"Supabase request failed with HTTP {exc.code}: {details}") from exc
                last_error = exc
            except urllib.error.URLError as exc:
                if not _is_transient_url_error(exc) or attempt == SUPABASE_REQUEST_MAX_ATTEMPTS:
                    raise ProductionStoreError(f"Supabase request failed: {exc.reason}") from exc
                last_error = exc
            time.sleep(SUPABASE_REQUEST_RETRY_SECONDS * attempt)

        raise ProductionStoreError(f"Supabase request failed after retries: {last_error}")


def _is_transient_url_error(exc: urllib.error.URLError) -> bool:
    reason = exc.reason
    if isinstance(reason, TimeoutError):
        return True
    if isinstance(reason, OSError):
        return reason.errno in TRANSIENT_URL_ERROR_ERRNOS
    return False
