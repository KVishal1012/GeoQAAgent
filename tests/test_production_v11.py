from __future__ import annotations

from datetime import datetime, timedelta, timezone
import errno
import urllib.error
from pathlib import Path

import pytest

from geoqa.config import load_app_config
from geoqa.production.store import LocalProductionStore, ProductionStoreError, SupabaseProductionStore
from geoqa.production.worker import process_next_run


def _configure_local(monkeypatch, tmp_path, **extra: str) -> None:
    monkeypatch.setenv("GEOQA_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def _write_geojson(path: Path) -> None:
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"asset_id":"a"},"geometry":{"type":"Point","coordinates":[-79.38,43.65]}}]}',
        encoding="utf-8",
    )


def test_upload_init_rejects_large_file_mode_without_supabase(monkeypatch, tmp_path):
    _configure_local(monkeypatch, tmp_path, GEOQA_LARGE_FILE_MODE="true")
    store = LocalProductionStore(load_app_config())

    with pytest.raises(ProductionStoreError, match="Large-file mode requires Supabase"):
        store.create_upload_session(filename="large.geojson", size_bytes=10, content_type="application/geo+json")


def test_local_upload_session_and_completion_validate_metadata(monkeypatch, tmp_path):
    _configure_local(monkeypatch, tmp_path)
    store = LocalProductionStore(load_app_config())

    session = store.create_upload_session(filename="roads.geojson", size_bytes=42, content_type="application/geo+json")
    complete = store.complete_upload(
        upload_id=session["upload_id"],
        filename=session["filename"],
        storage_path=session["storage_path"],
        size_bytes=session["size_bytes"],
        content_type=session["content_type"],
    )

    assert session["direct_upload"] is False
    assert session["fallback_upload_url"] == "/api/v1/uploads"
    assert complete["upload_completed_at"]




def test_supabase_large_upload_requires_public_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    store = SupabaseProductionStore(load_app_config())

    with pytest.raises(ProductionStoreError, match="SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY"):
        store.create_upload_session(filename="large.geojson", size_bytes=7 * 1024 * 1024, content_type="application/geo+json")


def test_supabase_large_upload_session_uses_resumable_public_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable")
    store = SupabaseProductionStore(load_app_config())

    session = store.create_upload_session(filename="large.geojson", size_bytes=7 * 1024 * 1024, content_type="application/geo+json")

    assert session["direct_upload"] is True
    assert session["resumable_upload"] is True
    assert session["resumable_upload_url"] == "https://example.storage.supabase.co/storage/v1/upload/resumable"
    assert session["resumable_headers"]["Authorization"] == "Bearer publishable"
    assert session["resumable_headers"]["apikey"] == "publishable"
    assert session["resumable_headers"]["x-upsert"] == "true"
    assert session["resumable_chunk_bytes"] == 6 * 1024 * 1024
    assert "upload_url" not in session



class _FakeResponse:
    def __init__(self, payload: bytes = b"{}") -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload

    def close(self) -> None:
        return None


def test_supabase_request_retries_transient_device_busy(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    store = SupabaseProductionStore(load_app_config())
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError(OSError(errno.EBUSY, "Device or resource busy"))
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("geoqa.production.store.time.sleep", lambda seconds: None)

    payload = store._request_json(urllib.request.Request("https://example.supabase.co/rest/v1/geoqa_runs"))

    assert payload == {"ok": True}
    assert calls["count"] == 2


def test_supabase_request_retries_transient_http_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    store = SupabaseProductionStore(load_app_config())
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                "https://example.supabase.co/rest/v1/geoqa_runs",
                503,
                "Service Unavailable",
                hdrs=None,
                fp=_FakeResponse(b"temporary"),
            )
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("geoqa.production.store.time.sleep", lambda seconds: None)

    payload = store._request_json(urllib.request.Request("https://example.supabase.co/rest/v1/geoqa_runs"))

    assert payload == {"ok": True}
    assert calls["count"] == 2

def test_worker_claim_prevents_duplicate_processing(monkeypatch, tmp_path):
    _configure_local(monkeypatch, tmp_path, GEOQA_WORKER_ID="worker-a")
    store = LocalProductionStore(load_app_config())
    upload_path = tmp_path / "input.geojson"
    _write_geojson(upload_path)
    store.create_run(upload_id="upload-1", filename="input.geojson", upload_storage_path=str(upload_path))

    claimed = store.claim_next_run(worker_id="worker-a", stale_after_seconds=900, max_attempts=3)
    duplicate = store.claim_next_run(worker_id="worker-b", stale_after_seconds=900, max_attempts=3)

    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["claimed_by"] == "worker-a"
    assert claimed["attempt_count"] == 1
    assert duplicate is None


def test_stale_running_job_can_be_reclaimed(monkeypatch, tmp_path):
    _configure_local(monkeypatch, tmp_path)
    store = LocalProductionStore(load_app_config())
    upload_path = tmp_path / "input.geojson"
    _write_geojson(upload_path)
    run = store.create_run(upload_id="upload-1", filename="input.geojson", upload_storage_path=str(upload_path))
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    store.update_run(run["run_id"], status="running", claimed_by="old-worker", claimed_at=stale_time, last_heartbeat_at=stale_time)

    reclaimed = store.claim_next_run(worker_id="new-worker", stale_after_seconds=30, max_attempts=3)

    assert reclaimed is not None
    assert reclaimed["run_id"] == run["run_id"]
    assert reclaimed["claimed_by"] == "new-worker"
    assert reclaimed["attempt_count"] == 1


def test_failed_worker_attempt_requeues_then_stops_at_max_attempts(monkeypatch, tmp_path):
    _configure_local(monkeypatch, tmp_path, GEOQA_WORKER_MAX_ATTEMPTS="2")
    store = LocalProductionStore(load_app_config())
    missing_upload = tmp_path / "missing.geojson"
    run = store.create_run(upload_id="upload-1", filename="missing.geojson", upload_storage_path=str(missing_upload))

    first = process_next_run(store=store)
    second = process_next_run(store=store)

    assert first is not None
    assert first["status"] == "queued"
    assert first["attempt_count"] == 1
    assert second is not None
    assert second["status"] == "failed"
    assert second["attempt_count"] == 2
    assert second["error"] == "GeoQA processing failed. Review the worker logs for details."
