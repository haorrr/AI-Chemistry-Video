---
phase: 1
title: "Project Skeleton & Health Endpoint"
status: completed
priority: P1
effort: "1h"
dependencies: []
---

# Phase 1: Project Skeleton & Health Endpoint

## Overview
Bootstrap the FastAPI project structure, dependencies, and a working `/health` endpoint.
Maps to master prompt §18 Step 1.

## Requirements
- Functional: `uvicorn app.main:app --reload` starts; `GET /health` returns `{"status": "ok"}`.
- Non-functional: folder layout matches master prompt §9 (simplify only if truly needed, keep
  API/job/generation/artifact/render boundaries visible even if simplified).

## Architecture
Flat `app/` package with `api/`, `services/`, `utils/` subpackages (empty stubs OK for services
not yet implemented — `job_service.py`, `topic_registry.py` etc. get real content in Phase 2+).
`config.py` centralizes paths (`ARTIFACTS_DIR`, `SAMPLE_OUTPUTS_DIR`) so no hardcoded paths later.
`artifact_store.py` is created here (not deferred) since every later phase depends on it for
path construction — it's foundational infra, not phase-specific logic.
`main.py` sets up a FastAPI `lifespan` context manager that owns `app.state.background_tasks:
set[asyncio.Task]`, empty at startup — populated later by Phase 6, drained on shutdown here.
<!-- Updated: Validation Session 2 (PLAN_REVIEW #2, #7) -->

## Related Code Files
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/config.py`
- Create: `app/models.py` (stub — `JobStatus` enum only for now)
- Create: `app/api/__init__.py`
- Create: `app/api/video_requests.py` (router stub, health check can live in `main.py` directly)
- Create: `app/services/__init__.py`
- Create: `app/services/artifact_store.py`
- Create: `app/utils/__init__.py`
- Create: `app/utils/logging.py`
- Create: `artifacts/.gitkeep`
- Create: `sample_outputs/.gitkeep`

## Implementation Steps
1. `requirements.txt`: fastapi, uvicorn, pydantic, pillow, `moviepy>=2,<3` (pinned — 2.x renamed
   most `.set_*()` clip methods to `.with_*()`, don't mix API generations), edge-tts, pyttsx3
   (offline TTS fallback), python-multipart (if needed), pytest, httpx (TestClient dep).
   <!-- Updated: Validation Session 2 (PLAN_REVIEW #4) -->
2. `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `artifacts/*` (keep `.gitkeep`), `.env`.
3. `app/config.py`: `BASE_DIR`, `ARTIFACTS_DIR = BASE_DIR / "artifacts"`, `SAMPLE_OUTPUTS_DIR`, ensure dirs exist on import via `mkdir(parents=True, exist_ok=True)`.
4. `app/services/artifact_store.py` (PLAN_REVIEW #7):
   - `create_job_directory(job_id: str) -> Path` — validates `job_id` is a well-formed UUID
     (`uuid.UUID(job_id)`, reject otherwise) before touching the filesystem, creates
     `artifacts/{job_id}/` and `artifacts/{job_id}/slides/`.
   - `storyboard_path(job_id) -> Path`, `audio_path(job_id) -> Path`, `video_path(job_id) -> Path`,
     `slides_directory(job_id) -> Path` — pure path builders, all under `ARTIFACTS_DIR`.
   - `atomic_write_bytes(path: Path, data: bytes) -> None` / `atomic_write_json(path, obj)` —
     write to `path.with_suffix(path.suffix + ".tmp")` then `os.replace()` to the final path, so a
     crash mid-write never leaves a half-written artifact.
   - This module is the *only* place in the codebase allowed to construct `artifacts/...` paths
     from a `job_id` — every other service imports from here instead of hardcoding paths.
5. `app/utils/logging.py`: basic `logging.getLogger("chemistry_video")` config, reusable `get_logger()`.
6. `app/main.py`:
   - `@asynccontextmanager async def lifespan(app)`: on startup, `app.state.background_tasks =
     set()`; on shutdown, `await asyncio.gather(*app.state.background_tasks, return_exceptions=True)`
     (or cancel with a timeout) so in-flight pipeline tasks aren't abandoned mid-write.
     (PLAN_REVIEW #2 — actual task scheduling/registration happens in Phase 6, this phase only
     creates the empty registry and shutdown drain.)
   - create `FastAPI(lifespan=lifespan)` app, mount API router, add `GET /health` returning
     `{"status": "ok"}`.
7. Verify app starts and `/health` responds `200`.

## Success Criteria
- [x] `uvicorn app.main:app --reload` starts without error.
- [x] `curl http://localhost:8000/health` returns `{"status": "ok"}`.
- [x] Folder structure present, no hardcoded paths outside `config.py`/`artifact_store.py`.
- [x] `artifact_store.create_job_directory("not-a-uuid")` raises instead of creating a directory.

## Completion Notes (code-reviewer, 2026-07-19)
Verified live: `pytest tests/` 6/6 pass; `python -c "import app.main"` clean; real `uvicorn`
process started and `curl /health` returned `200 {"status":"ok"}` (process cleaned up after).
Function names in `artifact_store.py` (`create_job_directory`, `storyboard_path`, `audio_path`,
`video_path`, `slides_directory`, `atomic_write_bytes`, `atomic_write_json`) match every
downstream reference in Phases 2-6 exactly — confirmed via grep across all phase files. No
regressions or contract breaks found. Score 9/10 — one non-blocking suggestion (add a
`.tmp`-orphan-on-failure test) logged in the review report; no code changes required before
Phase 2. See `plans/reports/code-reviewer-260719-0033-phase1-review.md` for full findings.

## Risk Assessment
Low risk — pure scaffolding. Main pitfall: forgetting to create `artifacts/`/`sample_outputs/`
dirs, causing later `FileNotFoundError`. Mitigated by `config.py` ensuring dirs on import.
Note (Validation Session 1): `ffmpeg` is NOT on PATH in this dev environment — it's a system
prerequisite (not a pip package) needed by Phase 5/6; install it now to avoid a mid-project
blocker later (see Phase 5 for install instructions).
