"""Async orchestration: storyboard -> audio -> render -> completed.

Owns run_job() only. Job state (status/steps/error/paths) lives entirely in
job_service.py — this module calls into job_service, never the other way
around, and never mutates job records directly.
"""

import asyncio

from app.models import JobStatus
from app.services import audio_service, job_service, storyboard_generator, video_renderer
from app.utils.logging import get_logger

logger = get_logger(__name__)

_RENDER_SEMAPHORE = asyncio.Semaphore(2)  # caps concurrent MoviePy renders


async def run_job(job_id: str) -> None:
    try:
        job = job_service.get_job(job_id)

        job_service.update_job(job_id, status=JobStatus.generating_storyboard)
        storyboard = storyboard_generator.generate_storyboard(job.concept)
        storyboard_path = storyboard_generator.save_storyboard(job_id, storyboard)
        job_service.update_job(
            job_id, storyboard_path=storyboard_path, step="storyboard_generated"
        )

        job_service.update_job(job_id, status=JobStatus.validating_storyboard)
        # Construction of `storyboard` above already ran Pydantic validation
        # (Storyboard/Scene field_validators) — success here means it passed.
        job_service.update_job(job_id, step="storyboard_validated")

        job_service.update_job(job_id, status=JobStatus.generating_audio)
        narration = await audio_service.generate_narration(job_id, storyboard)
        job_service.update_job(
            job_id, audio_path=narration.combined_path, step="audio_generated"
        )

        job_service.update_job(job_id, status=JobStatus.rendering_video)
        async with _RENDER_SEMAPHORE:
            video_path = await asyncio.to_thread(
                video_renderer.render_video, job_id, storyboard, narration
            )
        # render_video() already calls validate_video() internally before
        # returning (raises VideoValidationError on a broken artifact), so the
        # file at video_path is already known-good — no separate call needed.
        job_service.update_job(job_id, artifact_path=video_path, step="video_rendered")

        job_service.update_job(job_id, step="artifact_saved")
        job_service.update_job(job_id, status=JobStatus.completed, step="job_completed")
        logger.info(f"Pipeline completed for job_id={job_id}")
    except Exception as e:
        logger.exception(f"Pipeline failed for job_id={job_id}")
        job_service.update_job(job_id, status=JobStatus.failed, error=str(e))
