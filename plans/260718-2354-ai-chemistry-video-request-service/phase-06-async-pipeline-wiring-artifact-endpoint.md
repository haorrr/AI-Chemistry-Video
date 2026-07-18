---
phase: 6
title: "Async Pipeline Wiring & Artifact Endpoint"
status: pending
priority: P1
effort: "3-4h"
dependencies: [5]
---

# Phase 6: Async Pipeline Wiring & Artifact Endpoint

## Overview
Wire storyboard → audio → render into one async background task triggered on job creation, with
status/step updates at each stage and explicit failure handling. Orchestration lives in a new
`pipeline_service.py`, kept separate from `job_service.py` (CRUD-only). Blocking work is
offloaded via `asyncio.to_thread` behind a concurrency-limiting semaphore, and the
`asyncio.create_task` reference is tracked so it can't be silently garbage-collected. Add the
artifact-retrieval endpoint. Maps to master prompt §6, §12, §18 Steps 7-8.
<!-- Updated: Validation Session 2 - pipeline_service split (PLAN_REVIEW #6), to_thread + semaphore
(PLAN_REVIEW #1), task registry (PLAN_REVIEW #2), artifact validation before completed
(PLAN_REVIEW #12), per-scene audio/video wiring (PLAN_REVIEW #8) -->

**Async mechanism confirmed (Validation Session 1): `asyncio.create_task`, not FastAPI
`BackgroundTasks`.** Starlette's `TestClient` (used by `run_demo.py`, Phase 7) runs
`BackgroundTasks` synchronously before the request call returns, which would make status polling
pointless — the job would already be `completed` on the very first `GET`. `asyncio.create_task`
genuinely backgrounds the work under the ASGI event loop.

## Requirements
- Functional: `POST /video-requests` triggers the full pipeline asynchronously (via
  `asyncio.create_task`, see Overview) without blocking the response.
- Functional: job status transitions through all 7 lifecycle states correctly; `steps` list
  reflects meaningful step names per master prompt §7 example
  (`job_created, storyboard_generated, storyboard_validated, audio_generated, video_rendered,
  artifact_saved, job_completed`).
- Functional: `GET /video-requests/{job_id}/artifact` returns `video/mp4` on completed, `409`
  on processing/failed, `404` on missing job, and `500`/clear error if metadata says `completed`
  but the artifact file no longer exists on disk (PLAN_REVIEW #12).
- Functional: `render_video` (blocking) runs via `await asyncio.to_thread(...)`, gated by a
  module-level `asyncio.Semaphore(2)` so at most 2 renders run concurrently (PLAN_REVIEW #1).
- Functional: the `asyncio.Task` created for each job is stored in `app.state.background_tasks`
  and removed via `add_done_callback` on completion; the app's `lifespan` shutdown (Phase 1)
  awaits/cancels any still-running tasks instead of abandoning them (PLAN_REVIEW #2).
- Functional: `video.mp4` is validated (`video_renderer.validate_video()`) **before** the job is
  marked `completed`; a validation failure marks the job `failed` with a clear error instead of
  silently completing with a broken artifact (PLAN_REVIEW #12).
- Non-functional: any step failure sets `status=failed` + populates `error` with a useful
  message; pipeline never leaves a job stuck in an intermediate status on exception.

## Architecture
`pipeline_service.py` (new module, PLAN_REVIEW #6) owns `async def run_job(job_id: str) -> None`
— the orchestrator. `job_service.py` stays CRUD-only (`create_job`/`list_jobs`/`get_job`/
`update_job`); `pipeline_service` imports and calls it, never the other way around. Each stage:
update status via `job_service.update_job(...)` → call the relevant service → append step → on
exception, catch, set `status=failed`, `error=str(e)`, log, return early (no further steps run).

```text
services/
├── job_service.py       # CRUD and state transitions only
├── pipeline_service.py  # orchestration — NEW, owns run_job()
├── artifact_store.py
├── storyboard_generator.py
├── audio_service.py
└── video_renderer.py
```

## Related Code Files
- Create: `app/services/pipeline_service.py`
- Modify: `app/api/video_requests.py` — trigger `pipeline_service.run_job` as a tracked
  `asyncio.create_task` on `POST /video-requests`; add `GET /video-requests/{job_id}/artifact`
  handler.
- Modify: `app/main.py` — nothing new here beyond Phase 1's task-registry/lifespan skeleton;
  this phase is the first to actually populate `app.state.background_tasks`.
- Modify: `app/models.py` — no change expected; `artifact_url` stays a pure string format in the
  API layer.

## Implementation Steps
1. `pipeline_service.py`:
   ```python
   _RENDER_SEMAPHORE = asyncio.Semaphore(2)  # cap concurrent MoviePy renders

   async def run_job(job_id: str) -> None:
       try:
           job_service.update_job(job_id, status=JobStatus.generating_storyboard)
           storyboard = storyboard_generator.generate_storyboard(job.concept)
           storyboard_generator.save_storyboard(job_id, storyboard)
           job_service.update_job(job_id, status=..., steps_append="storyboard_generated")

           job_service.update_job(job_id, status=JobStatus.validating_storyboard)
           # construction success == validation pass (Pydantic already enforced it)
           job_service.update_job(job_id, steps_append="storyboard_validated")

           job_service.update_job(job_id, status=JobStatus.generating_audio)
           narration = await audio_service.generate_narration(job_id, storyboard)
           job_service.update_job(job_id, steps_append="audio_generated")

           job_service.update_job(job_id, status=JobStatus.rendering_video)
           async with _RENDER_SEMAPHORE:
               video_path = await asyncio.to_thread(
                   video_renderer.render_video, job_id, storyboard, narration
               )
           # NOTE (code review, Phase 5): render_video() already calls validate_video()
           # internally before returning (raises on a broken artifact), so the video at
           # video_path is already known-good. No separate validate_video() call needed
           # here. If one is ever added for defense-in-depth, it MUST be wrapped in
           # asyncio.to_thread — validate_video() opens the file with VideoFileClip and
           # reads duration, which is blocking I/O/CPU work (same rule as render_video).
           job_service.update_job(job_id, steps_append="video_rendered")

           job_service.update_job(
               job_id,
               artifact_path=video_path, storyboard_path=..., audio_path=narration.combined_path,
               steps_append="artifact_saved",
           )
           job_service.update_job(job_id, status=JobStatus.completed, steps_append="job_completed")
       except Exception as e:
           logger.exception(f"Pipeline failed for job {job_id}")
           job_service.update_job(job_id, status=JobStatus.failed, error=str(e))
   ```
   (Pseudocode — adapt to whatever exact `update_job` signature Phase 2 settled on; the sequence
   and semaphore/to_thread placement are the load-bearing parts.)
2. `api/video_requests.py` `POST /video-requests`: after `job_service.create_job(...)`:
   ```python
   task = asyncio.create_task(pipeline_service.run_job(job.job_id))
   request.app.state.background_tasks.add(task)
   task.add_done_callback(request.app.state.background_tasks.discard)
   ```
   (PLAN_REVIEW #2 — without this, `task` has no strong reference and could be garbage-collected
   before completion.) Return `202 Accepted` + `Location` header (per Phase 2's decision).
3. `GET /video-requests/{job_id}/artifact`:
   - `404` if `job_service.get_job(job_id)` is `None`.
   - `409` with `{"status": job.status}` if not `completed` and not `failed`.
   - `409` with `{"status": "failed", "error": job.error}` if `failed`.
   - If `completed` but `not job.artifact_path.exists()`: this is an inconsistent-state case
     (metadata says done, file is gone) — return `500` with a clear message rather than letting
     `FileResponse` throw an unhandled error (PLAN_REVIEW #12).
   - `FileResponse(job.artifact_path, media_type="video/mp4")` if `completed` and file exists.
4. End-to-end manual test: `POST` one request, poll `GET /video-requests/{job_id}` until
   `completed`, then `GET .../artifact` and confirm a valid MP4 downloads. Also manually delete
   an artifact file after job completion and confirm the artifact endpoint returns a clear `500`
   instead of crashing.

## Success Criteria
- [ ] Creating a job returns `202 Accepted`; polling shows progression through all lifecycle
      statuses to `completed`.
- [ ] `steps` array matches the expected sequence from master prompt §7.
- [ ] Artifact endpoint returns correct status code + body for all 5 cases
      (completed/processing/failed/missing-job/completed-but-file-missing).
- [ ] Forcing a failure (e.g. temporarily break audio_service) results in `status=failed` with a
      populated `error`, not a hang or crash.
- [ ] Forcing `validate_video()` to fail (e.g. truncate a rendered file before validation runs)
      results in `status=failed`, not a false `completed`.
- [ ] Creating 3+ jobs concurrently doesn't exceed 2 simultaneous MoviePy renders (verify via
      logging timestamps or a temporary counter).
- [ ] `job_service.py` contains zero orchestration logic — `grep -n "def run_job\|def run_pipeline"
      app/services/job_service.py` returns nothing.

## Risk Assessment
This phase is the integration point — most likely place for subtle bugs (status races, the
semaphore/to_thread interaction, exceptions swallowed silently). Test the failure path
explicitly, not just the happy path, before moving to Phase 7. The task-registry pattern
(PLAN_REVIEW #2) only prevents *garbage-collection* of in-flight tasks; jobs and their tasks are
still lost on a hard process restart — that's the accepted in-memory-store limitation from
Validation Session 1, not a bug to fix here.
