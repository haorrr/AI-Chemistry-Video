# Code Review: Phase 2 — Job Model, Store, Topic Registry & Core Endpoints

## Scope
- Files reviewed: `app/models.py`, `app/services/topic_registry.py`, `app/services/job_service.py`,
  `app/api/video_requests.py`, `tests/test_phase2.py` (+ `app/services/artifact_store.py`,
  `app/main.py`, `app/config.py`, `app/utils/logging.py` from Phase 1 for boundary checks).
- LOC analyzed: ~230 new/changed.
- Focus: Phase 2 acceptance criteria, Phase 3-7 contract compatibility, master prompt §7/§8
  conformance, setattr/validation risk.
- Tests independently re-run (not just trusted from prior tester report): `pytest tests/ -v` →
  **23/23 passed** (6 Phase 1 + 17 Phase 2), 0.35s. `app.main` imports cleanly, router already
  mounted from Phase 1 (main.py untouched in this diff, confirmed via `git status`).

## Overall Assessment
Clean, in-scope implementation. Matches phase-02 spec almost line-for-line, respects the
job_service=CRUD-only / api=HTTP-only boundary, and the documented response contract exactly
matches master prompt §7. No regressions detected against Phase 3-7 assumptions. Score: **9/10**.

## Critical Issues
None.

## High Priority Findings
None.

## Medium Priority Improvements

**1. `job_service.update_job`'s `setattr` bypasses Pydantic validation (confirmed empirically).**
`Job` is a plain `BaseModel` (no `validate_assignment=True`). `update_job(job_id, **fields)` does
`setattr(job, key, value)` per field with no type/enum check. Verified directly:
```python
setattr(job, 'status', 'not_a_real_status')   # succeeds, job.status becomes a bare str
setattr(job, 'artifact_path', 12345)          # succeeds, job.artifact_path becomes an int
```
Since `JobStatus` is a `str, Enum`, correctly-spelled string statuses still compare equal to enum
members, so normal internal usage (callers always pass real `JobStatus.xxx` members, per Phase 6's
own pseudocode) won't break. Risk is narrow: a typo'd status string or a wrong-typed
`artifact_path`/`storyboard_path`/`audio_path` in Phase 6 would silently corrupt job state instead
of raising — e.g. `job.artifact_path.exists()` would blow up downstream with a confusing
`AttributeError: 'int' object has no attribute 'exists'` far from the actual bug site.
**Verdict: acceptable prototype tradeoff, not a blocker** — all current/planned callers are
internal and pass correctly-typed values. Suggest for later (not urgent): either add
`model_config = ConfigDict(validate_assignment=True)` to `Job`, or narrow `update_job`'s `**fields`
to an explicit keyword allowlist.

## Low Priority Suggestions

**2. Phase 6 pseudocode naming mismatch — heads-up, not a fix-now item.** Phase 6's draft
(`phase-06-async-pipeline-wiring-artifact-endpoint.md`) pseudocode calls
`job_service.update_job(job_id, status=..., steps_append="storyboard_generated")`. The actual
Phase 2 signature is `update_job(job_id, *, step: str | None = None, **fields)` — keyword is
`step` (singular, one step name per call), not `steps_append`. Phase 6's file already explicitly
labels this block "Pseudocode — adapt to whatever exact `update_job` signature Phase 2 settled on;
the sequence and semaphore/to_thread placement are the load-bearing parts," so this was
anticipated and is not a contract break. Flagging only so whoever implements Phase 6 doesn't
copy-paste the pseudocode verbatim. No gate-worthy regression.

**3. `update_job` raises a bare `KeyError` for an unknown `job_id`** (`_jobs[job_id]`, not
`.get()`). Not exercised by Phase 2's own endpoints (only `create_job`/`list_jobs`/`get_job` are
called from `api/video_requests.py`), so no current bug. Phase 6 will call `update_job` on
job_ids it just created itself, so this should stay a non-issue in practice — noting only in case
a future phase calls it on a possibly-stale id.

## Positive Observations
- Response contract is an exact field-for-field match to master prompt §7's documented JSON for
  all three endpoints (create/list/detail) — no drift, no extra/missing fields.
- `202 Accepted` + `Location` header implemented per plan.md PLAN_REVIEW #16, body unchanged as
  specified.
- Input normalization (trim, case-fold, 200-char cap, canonical-echo) implemented exactly per
  PLAN_REVIEW #17, with the canonical (registry-exact) string returned rather than raw user input.
- `job_service.create_job` correctly delegates directory creation to
  `artifact_store.create_job_directory(job_id)` — no path logic duplicated outside Phase 1's
  artifact_store module, respecting the "only artifact_store builds artifact paths" boundary.
- `job_service.py` contains zero orchestration logic (verified by inspection) — CRUD-only
  boundary from plan.md Architecture Summary is respected, ready for Phase 6's `pipeline_service.py`
  to layer on top without refactoring.
- `Job.steps` uses `Field(default_factory=list)` — no shared-mutable-default bug across instances.
- Test suite (`tests/test_phase2.py`) has proper isolation: autouse fixtures reset the in-memory
  `_jobs` dict and clean up `artifacts/` after every test; parametrized test covers all 3 supported
  queries; unit tests cover `topic_registry.resolve_concept` directly (not just via HTTP), including
  edge cases (empty string, `None`, oversized input, non-matching input).
- No dead code, no unused imports, consistent logging via `utils/logging.py` matching Phase 1's
  pattern.

## Recommended Actions
1. No required code changes to ship Phase 2 as-is.
2. (Optional, low urgency) Consider `validate_assignment=True` on `Job` or an explicit field
   allowlist in `update_job` before Phase 6 starts writing to more fields — cheap insurance against
   silent state corruption once orchestration adds more `update_job` call sites.
3. When implementing Phase 6, use `step=` (not `steps_append=`) and call `update_job` once per
   step transition, matching the signature already in `app/services/job_service.py`.

## Metrics
- Test Coverage: 23/23 passing (17 new Phase 2 tests + 6 Phase 1 regression tests), 0 failures.
- Lint/Type Issues: none run — no lint/type tooling in `requirements.txt` for this prototype stack
  (not a gap; out of scope per master prompt).
- Contract Match: 3/3 endpoints match master prompt §7 documented shapes exactly.

## Side Effects / Stop-and-Ask Gates
**None triggered.** No regressions against Phase 3-7 assumptions, no contract breaks, no naming
mismatch severe enough to block Phase 6 (it's pre-flagged pseudocode, and the real signature is
straightforward to adapt to). Safe to proceed to Phase 3.

## Unresolved Questions
None.
