"""Pydantic models shared across the API and services.

Populated incrementally: JobStatus here (Phase 1); Job/request/response models in
Phase 2; Scene/Storyboard in Phase 3; NarrationResult in Phase 4.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    generating_storyboard = "generating_storyboard"
    validating_storyboard = "validating_storyboard"
    generating_audio = "generating_audio"
    rendering_video = "rendering_video"
    completed = "completed"
    failed = "failed"


class Job(BaseModel):
    job_id: str
    query: str
    concept: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    steps: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    artifact_path: Optional[Path] = None
    storyboard_path: Optional[Path] = None
    audio_path: Optional[Path] = None


class VideoRequestCreate(BaseModel):
    query: str


class VideoRequestResponse(BaseModel):
    job_id: str
    query: str
    concept: str
    status: JobStatus
    message: str


class JobListItem(BaseModel):
    job_id: str
    query: str
    concept: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    artifact_url: str


class JobDetail(BaseModel):
    job_id: str
    query: str
    concept: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    steps: list[str]
    error: Optional[str] = None
    artifact_url: str
