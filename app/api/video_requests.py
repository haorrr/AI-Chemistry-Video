"""Video request endpoints. Create/list/detail implemented here (Phase 2);
artifact retrieval added in Phase 6. HTTP concerns only — business logic
lives in job_service/topic_registry."""

from fastapi import APIRouter, HTTPException, Response

from app.models import JobDetail, JobListItem, VideoRequestCreate, VideoRequestResponse
from app.services import job_service, topic_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _artifact_url(job_id: str) -> str:
    return f"/video-requests/{job_id}/artifact"


@router.post("/video-requests", response_model=VideoRequestResponse, status_code=202)
async def create_video_request(body: VideoRequestCreate, response: Response):
    resolved = topic_registry.resolve_concept(body.query)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported query. Supported queries: "
                + ", ".join(topic_registry.supported_queries())
            ),
        )
    canonical_query, concept = resolved
    job = job_service.create_job(canonical_query, concept)
    response.headers["Location"] = f"/video-requests/{job.job_id}"
    logger.info(f"Video request created: job_id={job.job_id} concept={concept}")
    return VideoRequestResponse(
        job_id=job.job_id,
        query=job.query,
        concept=job.concept,
        status=job.status,
        message="Video generation job created.",
    )


@router.get("/video-requests", response_model=list[JobListItem])
async def list_video_requests():
    return [
        JobListItem(
            job_id=job.job_id,
            query=job.query,
            concept=job.concept,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            artifact_url=_artifact_url(job.job_id),
        )
        for job in job_service.list_jobs()
    ]


@router.get("/video-requests/{job_id}", response_model=JobDetail)
async def get_video_request(job_id: str):
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobDetail(
        job_id=job.job_id,
        query=job.query,
        concept=job.concept,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        steps=job.steps,
        error=job.error,
        artifact_url=_artifact_url(job.job_id),
    )
