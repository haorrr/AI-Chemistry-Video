"""Phase 1 tests: app scaffolding, config, artifact_store, health check.

Phase 1 only implements scaffolding, config, artifact path management, and a
health check. No business endpoints exist yet (those land in later phases).
"""

import json
import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus
from app.services import artifact_store


# --- /health ---------------------------------------------------------------


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- artifact_store: create_job_directory -----------------------------------


def test_create_job_directory_creates_dir_and_slides_subdir():
    job_id = str(uuid.uuid4())
    directory = artifact_store.job_directory(job_id)
    try:
        result = artifact_store.create_job_directory(job_id)

        assert result == directory
        assert directory.is_dir()
        assert (directory / "slides").is_dir()
    finally:
        if directory.exists():
            shutil.rmtree(directory)


def test_create_job_directory_invalid_uuid_raises_value_error():
    with pytest.raises(ValueError):
        artifact_store.create_job_directory("not-a-valid-uuid")


def test_job_directory_invalid_uuid_raises_value_error():
    with pytest.raises(ValueError):
        artifact_store.job_directory("also-not-a-uuid")


# --- artifact_store: atomic_write_json --------------------------------------


def test_atomic_write_json_writes_readable_json_and_no_tmp_leftover():
    job_id = str(uuid.uuid4())
    directory = artifact_store.job_directory(job_id)
    try:
        target = artifact_store.storyboard_path(job_id)
        payload = {"job_id": job_id, "scenes": [1, 2, 3]}

        artifact_store.atomic_write_json(target, payload)

        assert target.exists()
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == payload

        leftover_tmp_files = list(target.parent.glob("*.tmp"))
        assert leftover_tmp_files == []
    finally:
        if directory.exists():
            shutil.rmtree(directory)


# --- models: JobStatus -------------------------------------------------------


def test_job_status_has_all_expected_values():
    expected = {
        "queued",
        "generating_storyboard",
        "validating_storyboard",
        "generating_audio",
        "rendering_video",
        "completed",
        "failed",
    }
    actual = {member.value for member in JobStatus}
    assert actual == expected
