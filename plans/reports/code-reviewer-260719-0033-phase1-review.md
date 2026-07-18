# Phase 1 Code Review — Project Skeleton & Health Endpoint

Plan: `plans/260718-2354-ai-chemistry-video-request-service/`
Score: **9/10**

## Scope
Files reviewed: `app/main.py`, `app/config.py`, `app/models.py`, `app/api/video_requests.py`,
`app/services/artifact_store.py`, `app/utils/logging.py`, `tests/test_phase1.py`,
`requirements.txt`, `.gitignore`, package `__init__.py` files, `artifacts/.gitkeep`,
`sample_outputs/.gitkeep`. ~150 LOC. Focus: Phase 1 acceptance criteria + regression risk for
Phases 2-7 (interface stability).

## Verification performed (not just read)
- `pytest tests/ -v` → 6/6 pass.
- `python -c "import app.main"` → clean import, no errors.
- Live `uvicorn app.main:app` process started on a scratch port, `curl /health` → `200
  {"status":"ok"}` (exact match), process killed after, no orphaned listener left behind.
- `git status --short` after tests → no leaked temp/artifact dirs (test `finally: shutil.rmtree`
  blocks work correctly).
- Grepped all 7 phase files for every `artifact_store.*` call site to confirm signature
  compatibility with what's implemented.

## (a) Success criteria — all 4 met
- `uvicorn` starts clean, `/health` returns exact `{"status": "ok"}` (verified live, not just via
  TestClient).
- Folder structure matches phase-01 spec exactly (`app/{api,services,utils}`, `artifacts/`,
  `sample_outputs/`, both with `.gitkeep`).
- `create_job_directory("not-a-uuid")` raises `ValueError` (test + manual confirm).
- No hardcoded artifact paths outside `config.py`/`artifact_store.py` — grepped, confirmed.

## (b) Interface compatibility for Phases 2-6 — no breaks found
Every function name plan.md and phase-02/03/04/05/06 reference by exact name exists with matching
signature: `create_job_directory(job_id)`, `storyboard_path(job_id)`, `audio_path(job_id)`,
`video_path(job_id)`, `slides_directory(job_id)`, `atomic_write_bytes(path, data)`,
`atomic_write_json(path, obj)`. All pure `Path`-returning builders route through the private
`job_directory()` helper (not in the plan's named list, but additive — doesn't remove or rename
anything phases 2-6 expect). No signature drift.

## (c) Public contracts (app object, lifespan, router) — match phase-06 expectations
`app.state.background_tasks: set[asyncio.Task] = set()` created in `lifespan` startup, drained
via `asyncio.gather(*pending, return_exceptions=True)` on shutdown — exactly the shape phase-06
step 2 assumes (`request.app.state.background_tasks.add(task)` /
`task.add_done_callback(request.app.state.background_tasks.discard)` will work unmodified against
a plain `set`). Router mounted via `app.include_router(video_requests_router)` before any routes
exist on it — safe, Phase 2 adding routes to the same `APIRouter()` instance requires no change
here. `/health` correctly lives directly on `app`, not the router, matching the phase-01 file's
explicitly offered option.

## (d) Conventions / path-traversal check
- Type hints present throughout, no dead code, no unused imports.
- `atomic_write_bytes`: `tempfile.mkstemp(dir=path.parent, suffix=".tmp")` (same-volume, so
  `os.replace` is atomic) → write inside `with os.fdopen(fd, "wb")` (fd always closed, exception
  or not) → `os.replace(tmp_name, path)`. On any exception, leftover tmp is removed if it still
  exists. No fd leak, no orphaned `.tmp` on any failure path traced (write failure, replace
  failure). Confirmed no leftover `.tmp` after successful write via test + manual grep.
- UUID/path-traversal check: `uuid.UUID(job_id)` only tolerates the literal substrings `urn:`,
  `uuid:`, and `{}`/`-` characters being stripped before requiring exactly 32 hex digits —
  anything containing `/`, `\`, or `..` fails `int(hex, 16)` and raises `ValueError` before any
  path is built. Traced through CPython's `uuid.UUID.__init__` stripping logic by hand — no
  traversal vector. (Minor edge case, not a vulnerability: a crafted string like
  `"uuid:xxxxxxxx-...".` passes UUID validation while still containing a literal colon; on
  Windows that would make `mkdir`/file ops raise `OSError` — not exploitable, just a confusing
  error if `job_id` were ever attacker-supplied on a GET path. Since `job_id` is always
  server-generated via `uuid.uuid4()` in Phase 2's `create_job`, this is theoretical for now —
  worth a one-line note in Phase 2 if `job_id` route params are ever trusted from client input
  beyond dict lookup.)

## Windows `os.replace` semantics — checked, no issue for this codebase
`os.replace` maps to `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING)` on Windows, which is atomic for
same-volume replacement — matches the POSIX guarantee this code relies on. The real Windows
divergence (`MoveFileEx` failing with `PermissionError`/`WinError 5` if the destination is open by
another process without `FILE_SHARE_DELETE`) doesn't apply here: every artifact path
(`storyboard.json`, `narration.mp3`, `video.mp4`) has exactly one writer per job and no code path
opens these files for reading while a write is in flight (Phase 6's artifact `FileResponse` only
serves after `status=completed`, i.e. after the write already succeeded). Flagging as a documented
non-issue given current single-writer usage, not a bug to fix.

## Critical Issues
None.

## High Priority Findings
None.

## Medium Priority Improvements
None blocking. One item below is a nice-to-have, not a gap against Phase 1 acceptance criteria.

## Low Priority Suggestions
- `tests/test_phase1.py` covers the atomic-write happy path but not the failure/cleanup path
  (e.g. simulate a write failure and assert no `.tmp` orphan). Code was traced by hand and is
  correct, but a regression test would catch future refactors breaking it. Not required for Phase
  1 sign-off — suggest picking up whenever `atomic_write_bytes` is touched again.
- `app.state.background_tasks: set[asyncio.Task] = set()` (annotated assignment on an attribute
  access) is valid Python and works, but reads slightly unusually; a plain
  `app.state.background_tasks = set()` with the type noted in a comment would be equally clear.
  Style-only, not worth changing.

## Positive Observations
- `artifact_store.py` cleanly enforces "only place that builds artifact paths from job_id" — every
  builder funnels through the validated `job_directory()`, so the UUID guard can't be bypassed by
  a new phase adding a path builder that forgets validation.
- Atomic write implementation is genuinely atomic and leak-free — correctly closes the fd via
  context manager before `os.replace`, and cleans up on every traced failure path.
- Task registry / lifespan shape in `main.py` is exactly what Phase 6's pseudocode assumes,
  verified by re-reading phase-06's implementation steps against the actual code — zero
  adaptation needed when Phase 6 lands.
- Test suite actually exercises the "raises, doesn't create a directory" contract as a real
  assertion (`pytest.raises(ValueError)`), not just a smoke test.

## Side effects requiring a stop-and-ask-user gate
None. No regressions, no contract breaks, no scope deviation from phase-01-start.md or plan.md.
Safe to proceed to Phase 2.

## Metrics
- Tests: 6/6 passing (`pytest tests/ -v`).
- Import/startup: clean (`python -c "import app.main"`, live `uvicorn` + `/health` 200 verified).
- Lint/type tooling: none configured in repo (no ruff/mypy config) — consistent with prototype
  scope in plan.md, not flagged as a gap.

## Unresolved questions
None.
