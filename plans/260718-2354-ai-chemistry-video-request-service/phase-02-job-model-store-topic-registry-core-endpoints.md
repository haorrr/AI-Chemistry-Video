---
phase: 2
title: "Job Model, Store, Topic Registry & Core Endpoints"
status: completed
priority: P1
effort: "2-3h"
dependencies: [1]
---

# Phase 2: Job Model, Store, Topic Registry & Core Endpoints

## Overview
Define the job data model, status lifecycle, in-memory persistence, the 3-concept topic
registry, and the create/list/detail endpoints (generation pipeline itself is wired in Phase 6 by
`pipeline_service.py` — here jobs are created with status `queued` and left there; `job_service`
stays CRUD-only, orchestration never lives here). Maps to master prompt §18 Steps 2-3.

## Requirements
- Functional: `POST /video-requests` creates a job (validates query via topic registry first);
  `GET /video-requests` lists all; `GET /video-requests/{job_id}` returns detail incl. `steps`.
- Functional: unsupported query → `400` with message listing the 3 supported queries.
- Functional: `POST /video-requests` returns `202 Accepted` (not `200`) with a `Location:
  /video-requests/{job_id}` header — the request is accepted for async processing, not yet
  complete. Response body format is unchanged. (PLAN_REVIEW #16)
- Functional: input normalization on the incoming `query` — trim whitespace, reject if length
  exceeds a sane cap (e.g. 200 chars) with `400`, match case-insensitively against the 3 known
  queries. Response echoes back the canonical (registry-exact) query string and resolved
  `concept`, not the raw user input. (PLAN_REVIEW #17)
- Non-functional: job service is the *only* writer of job state (per plan.md boundaries);
  orchestration logic does not belong in this phase or in `job_service.py` (see Phase 6's
  `pipeline_service.py`).

## Architecture
`topic_registry.py` maps exact query strings (case-sensitive per master prompt examples) to
concept keys (`ph_scale`, `covalent_bonds`, `ionic_vs_covalent`) — dict lookup, single source of
truth for "add a topic later". `job_service.py` wraps an in-memory `dict[str, Job]` behind
`create_job`, `list_jobs`, `get_job`, `update_job` functions — no direct dict access from the API
layer. <!-- Updated: Validation Session 1 - in-memory only, no JSON persistence (job state resets
on restart; acceptable for prototype/demo per user decision) -->


## Related Code Files
- Modify: `app/models.py` — add `JobStatus` enum (queued/generating_storyboard/
  validating_storyboard/generating_audio/rendering_video/completed/failed), `Job` model
  (job_id, query, concept, status, created_at, updated_at, steps: list[str], error: str|None,
  artifact_path, storyboard_path, audio_path), `VideoRequestCreate`, `VideoRequestResponse`,
  `JobListItem`, `JobDetail` response models.
- Create: `app/services/topic_registry.py`
- Create: `app/services/job_service.py`
- Modify: `app/api/video_requests.py` — implement POST/GET list/GET detail handlers, delegate to
  `job_service` + `topic_registry`.
- Modify: `app/main.py` — ensure router is included (if not already from Phase 1).
- Use (not create): `app/services/artifact_store.py` (from Phase 1) — call
  `artifact_store.create_job_directory(job.job_id)` on job creation so the folder exists before
  any later phase writes into it.

## Implementation Steps
1. `models.py`: `JobStatus(str, Enum)`, `Job(BaseModel)` with all fields from master prompt §8.
2. `topic_registry.py`:
   - `SUPPORTED_QUERIES: dict[str, str]` (canonical query string -> concept key).
   - `resolve_concept(raw_query: str) -> tuple[str, str] | None` — trims whitespace, caps input
     length (reject >200 chars before matching), matches case-insensitively against
     `SUPPORTED_QUERIES` keys, returns `(canonical_query, concept_key)` on match so the API layer
     can echo the canonical form back instead of the user's raw casing/whitespace. (PLAN_REVIEW #17)
   - `supported_queries() -> list[str]`.
3. `job_service.py`: module-level in-memory `dict[str, Job]`; `create_job(query, concept) -> Job`
   (status=`queued`, steps=["job_created"], calls `artifact_store.create_job_directory(job_id)`);
   `list_jobs() -> list[Job]`; `get_job(job_id) -> Job | None`; `update_job(job_id, **fields) ->
   Job` (always bumps `updated_at`, appends to `steps` when a step name is passed). **No
   orchestration logic here** — `run_pipeline`/equivalent lives in Phase 6's `pipeline_service.py`.
4. `api/video_requests.py`:
   - `POST /video-requests`: `topic_registry.resolve_concept(body.query)`; `400` listing
     `topic_registry.supported_queries()` if `None`; else `job_service.create_job(canonical_query,
     concept)`, return `VideoRequestResponse` with `status_code=202` and header
     `Location: /video-requests/{job.job_id}` (PLAN_REVIEW #16).
   - `GET /video-requests`: `job_service.list_jobs()` mapped to `JobListItem` (includes
     `artifact_url` computed as `/video-requests/{job_id}/artifact`).
   - `GET /video-requests/{job_id}`: `job_service.get_job()`, `404` if missing, else `JobDetail`.
5. Log job creation and status reads via `utils/logging.py`.

## Success Criteria
- [x] `POST /video-requests` with each of the 3 required queries returns `202 Accepted` +
      `status: queued` + `Location` header.
- [x] `POST /video-requests` with an unsupported query returns `400` listing the 3 supported queries.
- [x] `POST /video-requests` with `"  how does the ph scale work?  "` (whitespace + wrong case)
      still resolves to `ph_scale` and echoes the canonical query in the response.
- [x] `GET /video-requests` returns array including newly created jobs.
- [x] `GET /video-requests/{job_id}` returns `404` for unknown id, full detail for known id.
- [x] `artifacts/{job_id}/` directory exists immediately after job creation.

## Review Status (260719)
Code-reviewed and independently re-tested (23/23 pytest passing, all 6 criteria above verified
live via `TestClient`). Score 9/10 — no critical issues, no regressions for Phase 3-7, contract
matches master prompt §7 exactly. See
`../reports/code-reviewer-260719-0051-phase2-job-model-store-endpoints-review.md` for full
findings. One forward-note for Phase 6: its pseudocode's `steps_append=` kwarg doesn't exist —
actual signature is `update_job(job_id, *, step: str | None = None, **fields)` (single step name
per call). Phase 6's own file already flags its code as pseudocode-to-adapt, so this is not a
fix-now item, just a heads-up for whoever implements Phase 6.

**Next step:** proceed to Phase 3 (Storyboard Generation & Validation).

## Risk Assessment
Query matching is exact-string per master prompt (no fuzzy matching required/expected) — keep it
simple (dict lookup), don't over-engineer with NLP matching. In-memory store means job history is
lost on process restart — explicitly accepted (Validation Session 1) since the demo/prototype
runs within a single process lifetime.
