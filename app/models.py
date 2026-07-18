"""Pydantic models shared across the API and services.

Populated incrementally: JobStatus here (Phase 1); Job/request/response models in
Phase 2; Scene/Storyboard in Phase 3; NarrationResult in Phase 4.
"""

from enum import Enum


class JobStatus(str, Enum):
    queued = "queued"
    generating_storyboard = "generating_storyboard"
    validating_storyboard = "validating_storyboard"
    generating_audio = "generating_audio"
    rendering_video = "rendering_video"
    completed = "completed"
    failed = "failed"
