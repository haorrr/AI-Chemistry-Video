# AI Chemistry Video Request Service

## 1. Project Overview

A FastAPI backend prototype that turns a chemistry question into a short educational video. A
client submits one of three supported chemistry concept queries; the backend runs an async
pipeline (storyboard → narration audio → rendered slides → MP4 composition) and the client polls
for job status and downloads the finished video. Backend only — no frontend.

## 2. Supported Queries

Exactly three, matched case-insensitively with whitespace trimmed:

- `How does the pH scale work?`
- `Why do atoms form covalent bonds?`
- `What is the difference between ionic and covalent bonding?`

Any other query returns `400` listing these three.

## 3. Tech Stack

- **API**: FastAPI + Pydantic
- **Async jobs**: `asyncio.create_task` (tracked in `app.state.background_tasks`, drained on shutdown)
- **Persistence**: in-memory (single-process; see [Limitations](#12-limitations--future-improvements))
- **Slides**: Pillow
- **Video composition**: MoviePy 2.x
- **Narration**: `edge-tts` (primary) with `pyttsx3` offline fallback
- **Tests**: pytest (74 tests across `tests/test_phase1.py`–`test_phase6.py`)

## 4. Setup Instructions

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**ffmpeg**: not a required manual install. MoviePy 2.x depends on `imageio-ffmpeg`, which bundles
its own ffmpeg binary — confirmed working (audio + video rendering, including concurrent renders)
without any system ffmpeg on PATH throughout development of this project. If you hit a
codec/rendering error MoviePy can't resolve on your platform, installing a system ffmpeg build
(Windows: a static build from gyan.dev added to PATH, or `choco install ffmpeg`; Linux:
`apt install ffmpeg`; macOS: `brew install ffmpeg`) is a safe fallback, but isn't needed by default.

## 5. Run Instructions

```bash
uvicorn app.main:app --reload
```

Serves on `http://localhost:8000` by default. `GET /health` should return `{"status": "ok"}`.

## 6. API Examples (curl)

**Health check**

```bash
curl http://localhost:8000/health
```

**Create a video request** — returns `202 Accepted` with a `Location` header (the job is accepted
for async processing, not yet complete):

```bash
curl -i -X POST http://localhost:8000/video-requests \
  -H "Content-Type: application/json" \
  -d '{"query": "How does the pH scale work?"}'
```

```json
{
  "job_id": "...",
  "query": "How does the pH scale work?",
  "concept": "ph_scale",
  "status": "queued",
  "message": "Video generation job created."
}
```

An unsupported query returns `400` with the list of supported queries in `detail`.

**List all jobs**

```bash
curl http://localhost:8000/video-requests
```

**Get one job's status/detail** (poll this until `status` is `completed` or `failed`):

```bash
curl http://localhost:8000/video-requests/{job_id}
```

**Download the finished video**

```bash
curl -o video.mp4 http://localhost:8000/video-requests/{job_id}/artifact
```

Returns `video/mp4` if `completed`; `409` with the current status if still processing or failed;
`404` if the job doesn't exist; `500` if the job says `completed` but the file is missing (an
inconsistent-state safety net, not expected in normal operation).

## 7. Generating the Three Required Videos

```bash
python run_demo.py
```

Creates all 3 required jobs, polls each to completion, downloads and validates each artifact, and
copies them to `sample_outputs/{ph_scale,covalent_bonds,ionic_vs_covalent}.mp4`. Takes roughly
30-60 seconds total (2 renders run concurrently, capped by a semaphore — see
[ARCHITECTURE.md](./ARCHITECTURE.md)).

## 8. Retrieving Artifacts

Two ways:
1. **Via the API** — `GET /video-requests/{job_id}/artifact` (see §6 above).
2. **Directly on disk** — completed jobs' videos live at `artifacts/{job_id}/video.mp4`, alongside
   `storyboard.json`, `narration.mp3`, and the per-scene `slides/` PNGs used to build the video.

`sample_outputs/` holds the 3 canonical demo videos after running `run_demo.py`.

## 9. Demo / Test Instructions

```bash
python run_demo.py            # end-to-end demo, prints a pass/fail summary
pytest                        # full test suite (74 tests, ~45s)
pytest tests/test_phase6.py   # just the pipeline/artifact-endpoint tests
```

`run_demo.py` uses FastAPI's `TestClient` in-process — no separate server needed. The pipeline has
also been manually verified against a real `uvicorn` server + `curl` to confirm identical async
behavior under the real ASGI runtime, not just the in-process test simulation.

## 10. Cost-Efficiency Note

No paid AI video-generation APIs. Storyboards are deterministic templates (not LLM calls), slides
are rendered locally with Pillow, and video composition runs locally with MoviePy — the only
external cost is `edge-tts`'s free narration API, with a fully local `pyttsx3` fallback if that's
ever unavailable. Rendering happens entirely on the host machine; the only variable cost is compute
time, capped by a concurrency semaphore (see ARCHITECTURE.md).

## 11. Reliability Note

- Explicit job status lifecycle (`queued` → ... → `completed`/`failed`) with a `steps` audit trail.
- Storyboard schema validated by Pydantic; a broken primary template falls back to an independent,
  minimal, always-valid safe template rather than retrying the same broken one.
- Narration: `edge-tts` calls have a timeout + retry; a corrupt/failed output on any scene falls
  back to regenerating *all* scenes with `pyttsx3` (never mixes voices within one video).
- The rendered video is validated (duration, has audio+video streams) before a job is marked
  `completed` — a broken artifact fails the job instead of completing with garbage.
- All artifact writes (`storyboard.json`, `narration.mp3`, `video.mp4`) are atomic (temp file +
  rename) so a crash mid-write never leaves a corrupt file behind.
- Every stage logs start/success/failure; failures always resolve the job to `failed` with a
  populated `error` field, never leaving it stuck in an intermediate status.

## 12. Limitations & Future Improvements

- **In-memory job store, single process/worker.** No database. Restarting the server loses all
  job metadata; a job that's mid-pipeline when the process dies is lost (no resume). Artifact
  files on disk can outlive their job record after a restart (orphaned files). This is a deliberate
  prototype tradeoff (see the plan's Validation Log), not an oversight — the fix is a persistent
  database plus a durable queue/worker (e.g. Postgres/Redis + Celery/RQ) for a production version.
- **Only 3 supported concepts**, hardcoded in `app/services/topic_registry.py`. Adding more is
  straightforward (the registry, storyboard templates, and renderer are all designed to extend)
  but out of scope for this prototype.
- **No LLM/real AI provider integration.** `storyboard_generator.py` is deliberately isolated
  behind one function so a real LLM call could replace the deterministic templates later without
  touching any other module.
- **No auth/rate-limiting/multi-tenant concerns** — explicitly out of scope for this prototype.
- **Font**: text rendering uses a bundled DejaVu Sans TTF (`app/assets/fonts/`) for cross-platform
  consistency, falling back to common OS font paths, and raising loudly rather than silently
  degrading to unreadable text if none is found.
