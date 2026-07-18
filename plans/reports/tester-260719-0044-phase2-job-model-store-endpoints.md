# Phase 2 Testing Report: Job Model, Store, Topic Registry, Core Endpoints

## Scope
Wrote `tests/test_phase2.py` covering phase-02 Success Criteria. Ran full suite (Phase 1 + Phase 2).

## Test Results
Full suite: **23 passed, 0 failed, 0 skipped** (0.55s).
- Phase 1: 6/6 passed (untouched, no regressions).
- Phase 2: 17/17 passed (new file).

## Coverage of Success Criteria
- POST /video-requests x3 supported queries -> 202 + status queued + Location header (parametrized test, matches job_id via regex).
- POST unsupported query -> 400, detail lists all 3 supported queries.
- POST "  how does the ph scale work?  " -> resolves ph_scale, echoes canonical "How does the pH scale work?".
- POST query >200 chars -> 400, not 500.
- GET /video-requests -> includes newly created job w/ artifact_url.
- GET /video-requests/{job_id} -> 404 unknown UUID; full detail incl. steps=["job_created"] for known job.
- artifacts/{job_id}/ dir exists immediately after creation (filesystem check).
- topic_registry.resolve_concept() unit tests: exact match, case-insensitive, whitespace-trimmed, empty string, None input, too-long input, non-matching string — all direct (no HTTP).

## Isolation / Cleanup
- Added autouse fixture `reset_job_store` clearing `job_service._jobs` before/after each test (module-level in-memory dict persists across TestClient instances in same process).
- Added autouse fixture `cleanup_artifacts` removing any non-`.gitkeep` entries under `ARTIFACTS_DIR` after each test.
- Verified `artifacts/` contains only `.gitkeep` after full run — no leftover job directories.

## Bugs Found/Fixed
None. All source files (`app/models.py`, `app/services/topic_registry.py`, `app/services/job_service.py`, `app/api/video_requests.py`) matched phase spec exactly on first test run — no app code changes needed.

## Unresolved Questions
None.

Status: DONE
Summary: Added tests/test_phase2.py (17 tests) covering all Phase 2 success criteria; full suite 23/23 passing incl. Phase 1 regression check; no app bugs found; artifacts/ dir clean after run.
