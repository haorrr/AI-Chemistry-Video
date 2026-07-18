# Architecture

## Job Lifecycle

```text
request received
  -> job created (status=queued)
  -> async task started (asyncio.create_task, tracked in app.state.background_tasks)
  -> storyboard generated (status=generating_storyboard)
  -> storyboard validated (status=validating_storyboard)
  -> narration audio generated (status=generating_audio)
  -> video rendered + validated (status=rendering_video)
  -> artifact paths saved
  -> completed (status=completed)

  (any step's exception -> status=failed, error populated, remaining steps skipped)
```

Status enum: `queued -> generating_storyboard -> validating_storyboard -> generating_audio ->
rendering_video -> completed` (or `failed` at any point). Each job also carries a `steps: list[str]`
audit trail (`job_created`, `storyboard_generated`, `storyboard_validated`, `audio_generated`,
`video_rendered`, `artifact_saved`, `job_completed`).

## Backend Boundaries

```text
app/
├── main.py                    FastAPI app, lifespan (background-task registry), /health
├── models.py                  Pydantic: JobStatus, Job, request/response models,
│                               Scene/Storyboard, NarrationResult
├── config.py                  Centralized filesystem paths
├── api/
│   └── video_requests.py      HTTP layer only — no business logic
└── services/
    ├── job_service.py         Job CRUD + state transitions ONLY (no orchestration)
    ├── pipeline_service.py    Orchestrator — owns run_job(), calls the services below
    ├── topic_registry.py      Supported-concept scope (query -> concept_key)
    ├── storyboard_generator.py  Deterministic templates; the AI/LLM swap boundary
    ├── audio_service.py       edge-tts + pyttsx3 fallback, per-scene narration
    ├── video_renderer.py      MoviePy composition + validate_video()
    ├── render_templates.py    Pillow slide drawing (split out of video_renderer.py)
    └── artifact_store.py      artifacts/{job_id}/ path ownership, atomic writes
```

- **API layer** (`api/video_requests.py`): request/response shaping and HTTP status codes only.
  Delegates every decision to a service.
- **Job service**: the *only* writer of job records (in-memory dict). CRUD + state transitions —
  zero orchestration logic (enforced by a test that greps the file for `def run_job`/`def run_pipeline`).
- **Pipeline service**: owns the async orchestration (`run_job`). Calls `job_service` to read/write
  state; never the reverse. Kept as a separate module specifically so state-management and
  orchestration concerns don't blur into one file.
- **Topic registry**: single source of truth for the 3 supported concepts — the one place to touch
  when adding a topic later.
- **Storyboard generator**: the AI/LLM swap boundary (see below).
- **Audio service / Video renderer**: each independently swappable, each owns its own
  provider-specific reliability logic (retry, fallback, validation).
- **Artifact store**: the *only* module allowed to construct `artifacts/{job_id}/...` paths from a
  `job_id` (UUID-validated) and the only place atomic-write helpers live.

## Persistence / Artifact Boundary

Job **metadata** lives in an in-memory `dict[str, Job]` inside `job_service.py` — no database, no
external persistence. Job **artifacts** (storyboard JSON, narration MP3, slide PNGs, final MP4)
live on disk under `artifacts/{job_id}/`, owned exclusively by `artifact_store.py`. These are two
separate boundaries on purpose: metadata is process-lifetime only, but artifact files can outlive
the process (see Limitations in README.md) — the artifact endpoint explicitly handles the case
where metadata says `completed` but the file is gone (returns `500`, not a crash).

All artifact writes are atomic: written to a temp path in the same directory, validated, then
`os.replace()`'d into place. A crash mid-write never leaves a half-written file that a later read
would treat as valid.

## AI / Video Generation Boundary

This prototype uses **deterministic templates**, not a real AI/LLM call, for storyboard content —
a reliability and cost decision (see master prompt's rationale), not a technical limitation.
`storyboard_generator.py` exposes exactly one public function,
`generate_storyboard(concept: str) -> Storyboard`; every other module only sees the resulting
`Storyboard` object. Swapping in a real LLM provider later means rewriting the *inside* of that
one function — no other file changes. The same isolation pattern applies to narration
(`audio_service.generate_narration`) and rendering (`video_renderer.render_video`): each is a
single swappable function with everything provider-specific hidden behind it.

## Reliability Strategy

- **Validation at every boundary**: Pydantic validates the storyboard schema (3-6 scenes, known
  visual types); `video_renderer.validate_video()` checks the rendered file's existence, size,
  duration range (30-70s), and audio+video streams before a job is allowed to reach `completed`.
- **Fallback templates**: if a primary storyboard template raises, a genuinely different, minimal,
  independently-tested safe template is used instead of retrying the identical broken one.
- **Explicit status lifecycle + step tracking**: every stage transition is visible via `GET
  /video-requests/{job_id}` — no job is ever silently "doing something" with no observable state.
- **TTS resilience**: `edge-tts` calls carry a timeout + 2 retries with backoff; if a scene's
  output is corrupt or all retries are exhausted, *all* scenes are regenerated with the offline
  `pyttsx3` fallback (never mixes engines/voices within one video). Only fails the job if both
  engines fail.
- **Error messages + logging**: every service logs start/success/failure; any exception during the
  pipeline is caught once at the top of `pipeline_service.run_job`, logged with a full traceback,
  and turns into `status=failed` + a populated `error` field — a job is never left stuck mid-status.
- **Local deterministic rendering**: no network-dependent video generation API to be flaky about;
  the only network call in the whole pipeline is the optional `edge-tts` narration request.
- **Concurrency control**: a module-level `asyncio.Semaphore(2)` in `pipeline_service.py` caps
  concurrent MoviePy renders, and all blocking work (`render_video`, `pyttsx3` synthesis, MoviePy
  transcode/concat) is offloaded via `asyncio.to_thread` so the event loop stays responsive to
  status-polling requests while a render is in progress.
- **Background-task lifecycle**: every `asyncio.create_task` is held in `app.state.background_tasks`
  (preventing garbage collection mid-run) and drained on app shutdown, so in-flight jobs aren't
  silently abandoned when the process stops cleanly.

## Cost Strategy

- No paid AI video-generation APIs — storyboards are static templates, not LLM-generated.
- All rendering (slides, video composition) happens locally via Pillow + MoviePy; the only
  external network call is `edge-tts`'s free narration API, with a fully local fallback.
- Structured, deterministic templates make output repeatable and cheap to re-render for testing —
  no per-run generation cost variance.
- The AI/LLM provider boundary (see above) is isolated specifically so a future paid provider
  integration is an opt-in swap, not a rewrite — cost stays a deliberate choice, not baked into
  the architecture.
