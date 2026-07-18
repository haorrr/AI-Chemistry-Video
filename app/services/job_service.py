"""Job CRUD + status/step transitions ONLY. No orchestration logic here —
that lives in pipeline_service.py (Phase 6)."""

import uuid
from datetime import datetime, timezone

from app.models import Job, JobStatus
from app.services import artifact_store
from app.utils.logging import get_logger

logger = get_logger(__name__)

_jobs: dict[str, Job] = {}


def create_job(query: str, concept: str) -> Job:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    job = Job(
        job_id=job_id,
        query=query,
        concept=concept,
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
        steps=["job_created"],
    )
    artifact_store.create_job_directory(job_id)
    _jobs[job_id] = job
    logger.info(f"Job created: job_id={job_id} concept={concept}")
    return job


def list_jobs() -> list[Job]:
    return list(_jobs.values())


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def update_job(job_id: str, *, step: str | None = None, **fields) -> Job:
    job = _jobs[job_id]
    for key, value in fields.items():
        setattr(job, key, value)
    if step:
        job.steps.append(step)
    job.updated_at = datetime.now(timezone.utc)
    logger.info(f"Job updated: job_id={job_id} status={job.status} step={step}")
    return job
