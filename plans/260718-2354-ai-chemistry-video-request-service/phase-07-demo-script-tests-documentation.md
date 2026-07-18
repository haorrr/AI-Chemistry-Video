---
phase: 7
title: "Demo Script, Tests & Documentation"
status: completed
priority: P2
effort: "2-3h"
dependencies: [6]
---

# Phase 7: Demo Script, Tests & Documentation

## Overview
Final verification layer (demo script or pytest suite) proving all 3 required concepts work
end to end, plus README.md and ARCHITECTURE.md. Maps to master prompt §15-17, §18 Steps 9-10.

## Requirements
- Functional: running the demo generates all 3 required videos and copies them to
  `sample_outputs/{ph_scale,covalent_bonds,ionic_vs_covalent}.mp4`.
- Functional: minimum verification list from master prompt §15 all covered (create x3, list,
  detail, artifact-exists, unsupported-query-400).
- Documentation: README.md covers all 12 items in master prompt §16; ARCHITECTURE.md covers all
  sections in master prompt §17.

## Architecture
`run_demo.py` uses FastAPI's in-process `TestClient` (confirmed, Validation Session 1) **as a
context manager** — `with TestClient(app) as client:` — so the app's `lifespan` (task registry
from Phase 1) actually starts and stays alive for the duration of the POST + polling loop
(PLAN_REVIEW #3; using `TestClient(app)` without the `with` block risks the lifespan never
starting or background tasks not running reliably). Single command, no separately-managed server
process, and consistent with the `asyncio.create_task` choice in Phase 6 (genuinely backgrounds
work so polling shows real status progression, unlike `BackgroundTasks` which `TestClient` would
run synchronously). A `tests/test_api.py` using the same `TestClient` pattern is an
acceptable/complementary alternative for the required verification list; one is sufficient per
acceptance checklist. **In addition**, run the pipeline at least once against a real `uvicorn`
server (separate terminal, real HTTP client) to confirm async/background-task behavior holds
under the actual ASGI runtime, not just under `TestClient`'s in-process simulation
(PLAN_REVIEW #3).

## Related Code Files
- Create: `run_demo.py` (primary demo/verification path)
- Create (optional): `tests/test_api.py` if pytest-based verification is preferred/added
- Create: `README.md` (overwrite placeholder)
- Create: `ARCHITECTURE.md`

## Implementation Steps
1. `run_demo.py`:
   - Use in-process `TestClient` **as a context manager**:
     ```python
     with TestClient(app) as client:
         # all POST + polling calls go inside this block
         ...
     ```
     (confirmed choice, corrected usage per PLAN_REVIEW #3) — keeps the demo self-contained and
     runnable with one command while guaranteeing the app's lifespan/event loop are live.
   - `POST /video-requests` for all 3 required queries; expect `202 Accepted`.
   - Poll `GET /video-requests/{job_id}` until each reaches `completed` or `failed` (timeout
     guard, e.g. 5 min per job, since MoviePy render + edge-tts network round trip take real time).
   - On completion, copy `artifacts/{job_id}/video.mp4` to `sample_outputs/{concept}.mp4`; assert
     the copied file passes the same checks as `video_renderer.validate_video()` (duration
     30-70s, has audio+video streams) — don't just assert the file exists (PLAN_REVIEW #12).
   - Also exercise: `GET /video-requests` (list), `GET /video-requests/{job_id}` (detail),
     `POST /video-requests` with an unsupported query → assert `400`, `POST` with
     whitespace/wrong-case query → assert it still resolves (Phase 2's normalization).
   - Print a clear pass/fail summary per master prompt §15 minimum verification list.
   - Separately (not part of the automated script, a manual step): start `uvicorn app.main:app`
     in one terminal, run the same POST+poll sequence with a real HTTP client (`httpx.Client` or
     `curl` + a polling loop) against `http://localhost:8000` in another, confirm identical
     behavior to the `TestClient` run (PLAN_REVIEW #3).
2. `README.md` — write all 12 sections from master prompt §16, with the exact venv/uvicorn
   commands specified (including the Windows `.venv\Scripts\activate` variant), curl examples
   for each endpoint (reflecting `202 Accepted` responses), and explicit cost-efficiency +
   reliability + limitations notes. Setup section must document the ffmpeg manual-install
   prerequisite (Windows: static build on PATH, or `choco install ffmpeg`). Limitations section
   must explicitly cover (PLAN_REVIEW #18):
   - Single Uvicorn worker only — the in-memory job store is not shared across processes/workers.
   - Restarting the server loses all job metadata.
   - A job that's mid-pipeline when the process dies is lost (no resume/recovery).
   - Artifact files on disk can outlive their job metadata (orphaned files after a restart).
   - Production direction: persistent database + durable queue/worker (e.g. Celery/RQ + Postgres
     or Redis) instead of in-memory dict + `asyncio.create_task`.
   - The edge-tts → pyttsx3 fallback and why: works offline, engine used is logged per job.
3. `ARCHITECTURE.md` — write all sections from master prompt §17 (job lifecycle diagram, backend
   boundaries — including the `job_service` vs `pipeline_service` split, PLAN_REVIEW #6 —
   persistence/artifact boundary, AI/video generation boundary, reliability strategy, cost
   strategy) — reuse the "Architecture Summary" section of `plan.md` as a starting point but
   expand to full prose per the master prompt's outline.
4. Run the demo end-to-end; confirm all 3 sample videos exist, are valid MP4s, and pass
   `validate_video()`-equivalent checks. Generate the Phase 5 contact-sheet QA render for **all
   3** concepts and visually confirm readable, correctly-diagrammed slides (PLAN_REVIEW #14) —
   not just one smoke-tested concept.
5. Walk the master prompt §20 acceptance checklist item by item and confirm each box.

## Success Criteria
- [ ] `python run_demo.py` (or `pytest tests/test_api.py`) completes successfully, all 3 videos generated.
- [ ] `sample_outputs/` contains all 3 required MP4s, each passing duration/stream validation.
- [ ] `run_demo.py` uses `TestClient` as a context manager (verify by inspection — no direct
      `TestClient(app)` calls without a `with` block).
- [ ] At least one manual run completed against a real `uvicorn` server with matching behavior.
- [ ] Contact-sheet QA reviewed for all 3 concepts, not just one.
- [ ] README.md and ARCHITECTURE.md exist and cover all required sections, including the
      expanded in-memory-persistence limitations list.
- [ ] Master prompt §20 acceptance checklist fully satisfied.

## Risk Assessment
edge-tts network dependency is mitigated by the pyttsx3 fallback (Phase 4) — the demo should
succeed offline too; still worth a manual offline test run since it exercises the fallback path.
Full pipeline run (3 videos, each with real per-scene TTS + MoviePy render) may take several
minutes total — set a generous but bounded poll timeout in `run_demo.py`. The `TestClient`
context-manager requirement is easy to silently get wrong (code still "runs" without the `with`
block, it just doesn't reliably background tasks) — the live-`uvicorn` cross-check exists
specifically to catch that class of bug before considering the phase done.
