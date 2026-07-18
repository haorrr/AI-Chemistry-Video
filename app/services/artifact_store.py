"""Owns artifacts/{job_id}/ path construction and atomic writes.

The only module allowed to build artifact filesystem paths from a job_id.
Every other service imports from here instead of hardcoding paths.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

from app.config import ARTIFACTS_DIR


def _validate_job_id(job_id: str) -> None:
    try:
        uuid.UUID(job_id)
    except (ValueError, AttributeError, TypeError) as e:
        raise ValueError(f"job_id must be a valid UUID, got: {job_id!r}") from e


def job_directory(job_id: str) -> Path:
    _validate_job_id(job_id)
    return ARTIFACTS_DIR / job_id


def create_job_directory(job_id: str) -> Path:
    directory = job_directory(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    slides_directory(job_id).mkdir(parents=True, exist_ok=True)
    return directory


def storyboard_path(job_id: str) -> Path:
    return job_directory(job_id) / "storyboard.json"


def audio_path(job_id: str) -> Path:
    return job_directory(job_id) / "narration.mp3"


def video_path(job_id: str) -> Path:
    return job_directory(job_id) / "video.mp4"


def slides_directory(job_id: str) -> Path:
    return job_directory(job_id) / "slides"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def atomic_write_json(path: Path, obj: object) -> None:
    atomic_write_bytes(path, json.dumps(obj, indent=2).encode("utf-8"))
