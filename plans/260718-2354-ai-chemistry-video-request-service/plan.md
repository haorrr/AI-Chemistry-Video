---
title: "AI Chemistry Video Request Service"
description: "FastAPI backend prototype: async chemistry-explainer video generation with local slide+TTS rendering"
status: pending
priority: P1
effort: "1-2d"
tags: [fastapi, backend, video-generation, prototype]
created: 2026-07-18
---

# AI Chemistry Video Request Service

## Overview

Backend prototype (FastAPI) that accepts a chemistry-concept video request, runs an async
generation pipeline (storyboard → narration audio → rendered slides → MP4 composition), and
exposes job status + artifact retrieval. Scope is locked to 3 hardcoded concepts
(`ph_scale`, `covalent_bonds`, `ionic_vs_covalent`) using deterministic templates — no paid
AI video-gen APIs, no LLM calls. Full spec: `../../masterprompt_claude_ai_chemistry_video_service_code_only.md`.

Source of truth for behavior is the master prompt. This plan operationalizes its 10-step
implementation order into 7 execution phases; nothing in this plan should contradict it.

## Scope Decision

Master prompt already answers ak-plan's Step-0 scope questions explicitly: "Do not overbuild",
"Do not spend time supporting extra topics", "make reasonable assumptions and proceed". Treated
as **HOLD SCOPE** — build exactly what's specified, no more, no less. Mode: **fast** (spec has
zero ambiguity, greenfield repo, no research/scouting needed).

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | FastAPI service with `/health`, `/video-requests` (POST/GET/detail), `/video-requests/{id}/artifact` | P1 |
| 2 | Async pipeline: storyboard → validate → audio → render → compose → save, with step tracking | P1 |
| 3 | Deterministic templates for the 3 required concepts, isolated behind a swappable generation boundary | P1 |
| 4 | Local slide-based MP4 output (Pillow + MoviePy + edge-tts), no paid video-gen APIs | P1 |
| 5 | Demo script producing 3 sample videos in `sample_outputs/` + README + ARCHITECTURE docs | P2 |

## Non-Goals (explicitly out of scope per master prompt)

- No frontend.
- No support for topics beyond the 3 required queries.
- No real/paid AI video-generation provider integration (boundary only, not implementation).
- No auth, multi-user, or production deployment concerns.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Project Skeleton & Health Endpoint](./phase-01-start.md) | Completed |
| 2 | [Phase 2: Job Model, Store, Topic Registry & Core Endpoints](./phase-02-job-model-store-topic-registry-core-endpoints.md) | Completed |
| 3 | [Phase 3: Storyboard Generation & Validation](./phase-03-storyboard-generation-validation.md) | Pending |
| 4 | [Phase 4: Audio Narration Service](./phase-04-audio-narration-service.md) | Pending |
| 5 | [Phase 5: Video Renderer (Slides + MP4 Composition)](./phase-05-video-renderer-slides-mp4-composition.md) | Pending |
| 6 | [Phase 6: Async Pipeline Wiring & Artifact Endpoint](./phase-06-async-pipeline-wiring-artifact-endpoint.md) | Pending |
| 7 | [Phase 7: Demo Script, Tests & Documentation](./phase-07-demo-script-tests-documentation.md) | Pending |

<!-- Updated: Validation Session 2 - filenames renumbered 01-07 sequentially (PLAN_REVIEW.md #19) -->

Phases run sequentially — each depends on the previous (job store needs skeleton; storyboard
needs job store; audio/render need storyboard; pipeline wiring needs audio+render; demo needs
the whole pipeline working end to end).

## Architecture Summary

```text
app/
├── main.py                    # FastAPI app, lifespan (task registry), router mount, /health
├── models.py                  # Pydantic: JobStatus enum, Job, requests/responses, Storyboard/Scene
├── config.py                  # Centralized paths (artifacts dir, etc.)
├── api/
│   └── video_requests.py      # Route handlers only — delegate to services
├── services/
│   ├── job_service.py         # Job CRUD + status/step transitions ONLY (no orchestration)
│   ├── pipeline_service.py    # Async orchestrator: storyboard -> audio -> render -> complete
│   ├── artifact_store.py      # artifacts/{job_id}/ path management, atomic writes, UUID guard
│   ├── topic_registry.py      # query -> concept_key mapping, supported-query validation
│   ├── storyboard_generator.py# deterministic + safe-fallback templates; AI/LLM boundary (swap point)
│   ├── audio_service.py       # edge-tts (+ pyttsx3 fallback), per-scene narration -> narration.mp3
│   └── video_renderer.py      # Pillow slides -> MoviePy MP4, artifact validation
└── utils/
    └── logging.py             # structured logger for lifecycle events
```
<!-- Updated: Validation Session 2 - added pipeline_service.py (PLAN_REVIEW #6), expanded artifact_store.py and audio/video service responsibilities (PLAN_REVIEW #7, #8, #12) -->

Boundaries (see master prompt §17 for the full ARCHITECTURE.md write-up):
- **API layer** (`api/`): HTTP only, no business logic.
- **Job service**: owns state + persistence (CRUD only) — the only writer of job records.
- **Pipeline service**: owns orchestration (the multi-step async flow) — calls job_service to
  update state, never owns state itself. Kept separate from job_service so state-management and
  orchestration boundaries don't blur (PLAN_REVIEW #6).
- **Topic registry**: owns supported-concept scope; single place to add topics later.
- **Storyboard generator**: the AI/LLM swap boundary — template-based now, provider-pluggable later.
- **Audio/Video services**: narration and rendering, each independently swappable.
- **Artifact store**: owns `artifacts/{job_id}/` file layout — the only module that builds
  artifact file paths (`create_job_directory`, `storyboard_path`, `audio_path`, `video_path`,
  `slides_directory`), validates `job_id` is a well-formed UUID before touching the filesystem,
  and writes atomically (temp file + rename).

## Job Lifecycle (status enum)

`queued → generating_storyboard → validating_storyboard → generating_audio → rendering_video → completed`
(or `failed` at any step, with `error` populated).

## Tech Stack

FastAPI, Pydantic, `asyncio.create_task` (background pipeline execution, run via a tracked task
registry — see Risks) with blocking work (`render_video`, `pyttsx3.runAndWait`) offloaded via
`asyncio.to_thread`, in-memory job store, Pillow (slides), `moviepy>=2,<3` (MP4 compose, `.with_*`
API, requires system ffmpeg), edge-tts (narration, primary, per-scene) with `pyttsx3` offline
fallback. <!-- Updated: Validation Session 2 - to_thread offloading, MoviePy 2.x pin (PLAN_REVIEW #1, #4) -->

## Success Criteria

- [ ] All endpoints in master prompt §7 implemented and match documented response shapes.
- [ ] All 3 required concepts produce a completed job with an MP4 artifact end to end.
- [ ] Unsupported query returns `400` with list of supported queries.
- [ ] Artifact endpoint returns correct status codes for processing/failed/not-found/completed.
- [ ] `sample_outputs/{ph_scale,covalent_bonds,ionic_vs_covalent}.mp4` exist after demo run.
- [ ] README.md and ARCHITECTURE.md present per master prompt §16-17.
- [ ] Acceptance checklist in master prompt §20 fully checked off.
- [ ] `POST /video-requests` returns `202 Accepted` with a `Location` header (PLAN_REVIEW #16).
- [ ] Each completed video is validated (exists, size>0, duration 30-70s, has audio+video
      streams) before the job is marked `completed` (PLAN_REVIEW #12).
- [ ] Slide durations are sized from actual per-scene narration audio, not an even split
      (PLAN_REVIEW #8, Validation Session 2).
- [ ] No `await`-blocking calls (MoviePy render, `pyttsx3.runAndWait`) run directly on the event
      loop — all offloaded via `asyncio.to_thread` (PLAN_REVIEW #1).

## Risks

- **edge-tts requires internet access** — mitigated by a `pyttsx3` offline fallback (see
  Validation Log); job only fails if *both* engines fail.
- **MoviePy/Pillow/ffmpeg system dependencies** — ffmpeg confirmed NOT on PATH in the dev
  environment as of plan validation. User chose manual system install over bundling
  `imageio-ffmpeg`; README must document the install step clearly (Windows: download static
  build, add to PATH, or `choco install ffmpeg`) — see Phase 7.
- **Windows path handling** — dev environment is Windows; use `pathlib` throughout, avoid
  hardcoded `/` separators, verify `artifacts/{job_id}/` creation works cross-platform.
- **Event loop blocking** — `render_video` (MoviePy, CPU/I/O heavy) and `pyttsx3.runAndWait`
  (sync) must never run directly inside an `async def`; both are dispatched via
  `asyncio.to_thread`, with a `asyncio.Semaphore(2)` capping concurrent renders so multiple
  simultaneous jobs don't starve the process (PLAN_REVIEW #1).
- **Fire-and-forget task loss** — `asyncio.create_task` results are held nowhere by default and
  can be garbage-collected mid-run. Mitigated by an `app.state` task registry (`set[Task]`) with
  `add_done_callback` cleanup and a lifespan shutdown hook that awaits/cancels outstanding tasks
  (PLAN_REVIEW #2). Jobs/tasks are still lost on hard process restart — documented, not solved
  (in-memory store is an accepted prototype limitation, see Validation Session 1 decision #1).
- **Per-scene TTS increases API call count** — per-scene narration (Validation Session 2 decision
  on slide timing) means 4-5 edge-tts calls per job instead of 1; if any scene call fails
  mid-batch, all scenes are regenerated with `pyttsx3` for engine/voice consistency rather than
  mixing engines within one video (see Phase 4).

## Validation Log

### Verification Results (Step 2.5)
- Claims checked: 8 (artifact paths, stack choices, endpoint behaviors vs master prompt; ffmpeg/python env probe)
- Verified: 7 | Failed: 0 | Unverified: 0
- Tier: Light (greenfield repo, no existing code to verify against — checked plan claims against master prompt text + live environment probe instead)
- Finding (not a plan failure, an environment fact): `ffmpeg` not found on PATH in this dev environment; `python 3.10.0` available. Surfaced as an interview question below.

### Interview Decisions (2026-07-18)
1. **Job persistence** → In-memory dict (Recommended). No JSON-file persistence; job state resets on restart, acceptable for prototype/demo.
2. **Async trigger** → `asyncio.create_task` (Recommended). Rejected `BackgroundTasks` because Starlette's `TestClient` runs those synchronously before the response returns, which would make the demo's polling loop (and the in-process `TestClient` demo driver chosen below) pointless.
3. **ffmpeg setup** → Require system ffmpeg install, documented in README (Windows instructions). Rejected `imageio-ffmpeg` bundling to keep dependencies minimal per master prompt's stack list, at the cost of a manual setup step.
4. **TTS fallback** → Add `pyttsx3` as an offline fallback engine: try `edge-tts` first, fall back to `pyttsx3` on failure (e.g. no internet), only mark the job `failed` if both fail. Reverses the initial "no fallback" draft — user explicitly wants resilience over minimalism here.
5. **Demo driver** → In-process FastAPI `TestClient` in `run_demo.py` (Recommended). Single-command, no separate server process needed. Consistent with decision #2 (`asyncio.create_task` actually executes under `TestClient`, unlike `BackgroundTasks`).
6. **Slide timing** → Even split of total narration duration across scenes (Recommended). Single `narration.mp3` per job stays consistent with master prompt §14's documented output path; per-scene audio files rejected as unnecessary complexity for a prototype.

### Whole-Plan Consistency Sweep (Session 1)
Re-read `plan.md` + all 7 phase files after propagating the above. Updated: Tech Stack section
(added pyttsx3, removed "JSON/in-memory" ambiguity → in-memory only), Risks section (ffmpeg +
TTS fallback reframed), Phase 2 (job store), Phase 4 (audio fallback), Phase 5 (ffmpeg
prerequisite check moved earlier, marked required not optional), Phase 6 (asyncio.create_task
confirmed, dropped BackgroundTasks as an option), Phase 7 (demo driver confirmed, README ffmpeg
install section added). No unresolved contradictions found.

## Validation Log — Session 2 (external code review: `PLAN_REVIEW.md`)

External review of the validated plan (2026-07-19) surfaced 15 concrete gaps/bugs across
correctness, architecture, and content accuracy. Applied fixes below; one item (slide timing)
reversed an explicit Session 1 decision and was re-confirmed with the user before changing.

### Applied directly (technical corrections/gap-fills, no conflict with prior user decisions)
- **#1 P0** — `render_video` and `pyttsx3.runAndWait` were previously implied to run inline in
  `async def run_pipeline`; both now explicitly dispatched via `asyncio.to_thread`, with a
  `asyncio.Semaphore(2)` limiting concurrent renders (Phase 5, Phase 6).
- **#2 P0** — `asyncio.create_task` results weren't referenced anywhere (GC risk). Added an
  `app.state` task registry + `add_done_callback` + lifespan shutdown drain (Phase 1, Phase 6).
- **#3 P0** — `run_demo.py`'s `TestClient` usage wasn't specified as a context manager (lifespan
  wouldn't start, background tasks wouldn't run reliably). Now explicit
  `with TestClient(app) as client:`; added a recommended one-time live-`uvicorn` smoke test
  (Phase 7).
- **#4 P0** — MoviePy version/API wasn't pinned (`.set_audio()` is 1.x-only, breaks on 2.x).
  Pinned `moviepy>=2,<3`, migrated to `.with_audio()`/`.with_duration()` (Phase 1, Phase 5).
- **#6 P1** — Orchestration was drafted inside `job_service.py`, blurring the CRUD-only boundary
  from Session 1. Moved to new `pipeline_service.py`; `job_service.py` stays state/CRUD only
  (Phase 6, plan.md Architecture Summary).
- **#7 P1** — `artifact_store.py` was named in the architecture diagram but never had concrete
  deliverables. Now explicit: `create_job_directory`, `storyboard_path`, `audio_path`,
  `video_path`, `slides_directory`, atomic temp-file+rename writes, UUID-only path construction
  (Phase 1, referenced by Phases 2-6).
- **#9 P1** — TTS had a fallback but no resilience within each engine. Added: per-call timeout,
  retry x2 with backoff on `edge-tts`, delete partial/empty output before falling back, verify
  output exists/size>0/readable-duration, log which engine actually produced the file (Phase 4).
- **#10 P1** — The "fallback" storyboard was literally the same deterministic template as
  primary — if a primary template had a schema bug, the fallback would fail identically. Added
  one generic `SAFE_FALLBACK_TEMPLATE` (3 scenes, safe visual types) used only if primary
  construction/validation raises; a fallback failure is treated as a config error (Phase 3).
- **#12 P1** — Jobs were marked `completed` on file existence alone. Added `validate_video()`
  (size, duration 30-70s, has audio+video streams, ffprobe/MoviePy-openable) called before
  `status=completed`; artifact endpoint now checks the file still exists even if metadata says
  completed (Phase 5, Phase 6).
- **#13 P1** — Content accuracy: pH scale now explicitly notes the logarithmic relationship
  (Δ1 pH ≈ 10x [H⁺]); covalent bonding wording softened from "always reach octet" to "generally
  reach a more stable configuration"; ionic-vs-covalent gets an explicit electron-transfer arrow
  visual, not just a table; added semantic keyword assertions per storyboard (Phase 3, Phase 5).
- **#14 P1** — "Readable text" had no verification criteria. Added: bundled font file (not
  relying on OS defaults), `textbbox`-based pixel-width wrapping, minimum font size/margin/
  contrast rules, a contact-sheet render step for visual QA across **all 3** concepts (not just a
  single smoke test) (Phase 5, Phase 7).
- **#16 P2** — `POST /video-requests` now returns `202 Accepted` + `Location` header (async job
  creation semantics); response body unchanged (Phase 2).
- **#17 P2** — Added light input normalization: trim whitespace, length cap, case-insensitive
  match within the 3 known queries, canonical query/concept echoed back in the response (Phase 2).
- **#18 P2** — README limitations section expanded: single-worker only, restart loses job
  metadata, an in-flight job dies with the process, artifact files can outlive their job record,
  production direction = persistent DB + durable queue/worker (Phase 7, plan.md Risks).
- **#19 P2** — Phase file numbering had a gap (`phase-03..08` for 7 phases, because an earlier
  duplicate stub was deleted without renumbering). Renamed to sequential `phase-01..07`; all
  `plan.md` links updated.

### Re-confirmed with user (reversed a Session 1 decision)
- **#8 P1 — Slide timing.** Session 1 chose "even split of total narration duration across
  scenes" for simplicity. PLAN_REVIEW correctly flagged this as an educational-quality risk
  (scenes with more/less narration text would desync from their slide). Presented 3 options
  (per-scene audio + exact sync / proportional word-count split + buffer / keep even split).
  **User selected: per-scene audio + exact sync.** `audio_service.generate_narration` now
  generates one clip per scene, measures each clip's duration, concatenates them into the single
  `narration.mp3` the master prompt documents, and returns per-scene durations for
  `video_renderer` to size each slide exactly (Phase 4, Phase 5, Phase 6).

### Whole-Plan Consistency Sweep (Session 2)
Re-read `plan.md` + all 7 renamed phase files after applying the above. Verified: no remaining
references to the old `phase-03..08` filenames, no remaining "even split" language outside the
historical Session 1 log entry (kept for audit trail), no remaining bare `job_service.run_pipeline`
references (all point to `pipeline_service.py`), MoviePy API calls consistently use `.with_*` (2.x)
across Phase 5/6, `artifact_store` referenced consistently by Phases 2-6 instead of ad-hoc path
building. No unresolved contradictions found — plan is internally consistent and ready for
implementation.

**Recommendation: proceed to `/ak:cook`.**

<!-- slug: ai-chemistry-video-request-service -->
