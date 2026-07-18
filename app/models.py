"""Pydantic models shared across the API and services.

Populated incrementally: JobStatus here (Phase 1); Job/request/response models in
Phase 2; Scene/Storyboard in Phase 3; NarrationResult in Phase 4.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SUPPORTED_CONCEPTS = {"ph_scale", "covalent_bonds", "ionic_vs_covalent"}


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


class Scene(BaseModel):
    heading: str
    visual_type: Literal["title", "ph_scale", "atom_sharing", "comparison_table", "summary"]
    visual_text: str
    narration: str


class Storyboard(BaseModel):
    title: str
    concept: str
    scenes: list[Scene] = Field(min_length=3, max_length=6)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v

    @field_validator("concept")
    @classmethod
    def concept_supported(cls, v: str) -> str:
        if v not in SUPPORTED_CONCEPTS:
            raise ValueError(f"unsupported concept: {v!r}")
        return v


@dataclass
class NarrationResult:
    """Internal service-to-service data, not an API contract — no Pydantic needed."""

    combined_path: Path
    scene_durations: list[float]
    engine_used: str
