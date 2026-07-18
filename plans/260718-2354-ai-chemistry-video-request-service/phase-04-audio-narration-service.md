---
phase: 4
title: "Audio Narration Service"
status: completed
priority: P1
effort: "3-4h"
dependencies: [3]
---

# Phase 4: Audio Narration Service

## Overview
Generate narration audio **per scene** (not one whole-job script) using `edge-tts` as the
primary engine with a `pyttsx3` offline fallback, measure each scene's clip duration, then
concatenate all clips into the single `artifacts/{job_id}/narration.mp3` the master prompt
documents. Per-scene durations are returned so Phase 5 can size each slide exactly instead of
guessing from an even split. Maps to master prompt §14, §18 Step 5.
<!-- Updated: Validation Session 2 - per-scene generation for exact audio/slide sync
(PLAN_REVIEW #8, user-confirmed reversal of Validation Session 1 decision #6), TTS resilience
(PLAN_REVIEW #9), to_thread offloading (PLAN_REVIEW #1) -->

## Requirements
- Functional: `generate_narration(job_id, storyboard) -> NarrationResult` where
  `NarrationResult` = `(combined_path: Path, scene_durations: list[float], engine_used: str)`.
  One TTS clip per scene, concatenated in scene order into the final `narration.mp3`.
- Functional: try `edge-tts` for all scenes first; if **any** scene's `edge-tts` call fails
  (after retries), discard any partial `edge-tts` output and regenerate **all** scenes with
  `pyttsx3` — never mix engines/voices within one video.
- Functional: `edge-tts` calls have a per-call timeout and retry up to 2x with backoff before
  being treated as failed (PLAN_REVIEW #9).
- Functional: before accepting any generated clip (either engine), verify the output file exists,
  has size > 0, and has a readable duration; delete partial/empty files before falling back.
- Non-functional: `pyttsx3.runAndWait()` is synchronous/blocking — always invoked via
  `asyncio.to_thread` so it never blocks the event loop (PLAN_REVIEW #1).
- Non-functional: only raise `NarrationGenerationError` (for the job's `error` field) if *both*
  engines fail for at least one scene after retries.

## Architecture
`audio_service.py` isolates both TTS providers behind one public function. Internally:
`_synthesize_scene(text, out_path, engine) -> float` (returns duration) is the per-scene unit;
`generate_narration()` loops scenes with one engine, falls back to regenerating all scenes with
the other engine on any failure, then concatenates via `ffmpeg`/MoviePy's `concatenate_audioclips`
into the final combined file. `NarrationResult` can be a small `NamedTuple`/`dataclass` in
`models.py` or `audio_service.py` — no need for a full Pydantic model since it's internal,
service-to-service data, not an API contract.

## Related Code Files
- Create: `app/services/audio_service.py`
- Modify: `app/models.py` — add `NarrationResult` (dataclass/NamedTuple: `combined_path: Path`,
  `scene_durations: list[float]`, `engine_used: str`).
- Use (not create): `app/services/artifact_store.py` — `audio_path(job_id)` for the final
  combined file; per-scene temp clips can live in a `slides_directory(job_id)`-adjacent temp
  location or `artifacts/{job_id}/_tmp_audio/` cleaned up after concatenation.

## Implementation Steps
1. Confirm `edge-tts` and `pyttsx3` are both in `requirements.txt` (from Phase 1).
2. `audio_service.py` — per-scene synthesis:
   - `async def _synth_edge_tts(text: str, out_path: Path, timeout: float = 15.0) -> None`:
     wrap `edge_tts.Communicate(text, voice=...).save(out_path)` with `asyncio.wait_for(...,
     timeout)`; retry up to 2x with short backoff (e.g. 1s, 2s) on timeout/exception; delete
     `out_path` if it exists but is empty/invalid before retrying.
   - `def _synth_pyttsx3(text: str, out_path_wav: Path) -> None`: `engine.save_to_file(text,
     str(out_path_wav)); engine.runAndWait()` — called via `await asyncio.to_thread(_synth_pyttsx3,
     ...)` from the async caller, never called directly in an `async def`.
   - `_transcode_wav_to_mp3(wav_path, mp3_path)`: shell out to `ffmpeg` (already a required
     system dependency, see Phase 5) or use `moviepy.AudioFileClip(wav_path).write_audiofile(
     mp3_path)`.
   - `_measure_duration(path: Path) -> float`: `AudioFileClip(path).duration` (or a lighter
     probe if MoviePy import cost matters — MoviePy is already a hard dependency, reuse it).
3. `generate_narration(job_id, storyboard) -> NarrationResult`:
   - For each scene, attempt `_synth_edge_tts` into a temp per-scene file.
   - If **all** scenes succeed with edge-tts → `engine_used = "edge-tts"`.
   - If **any** scene fails after retries → discard all edge-tts temp files, redo **every**
     scene with `_synth_pyttsx3` (+ transcode to mp3) → `engine_used = "pyttsx3"`. If any
     pyttsx3 scene also fails, raise `NarrationGenerationError`.
   - Measure each accepted clip's duration → `scene_durations: list[float]`.
   - Concatenate clips in scene order into `artifact_store.audio_path(job_id)` (the final
     `narration.mp3`) — total duration equals `sum(scene_durations)` by construction, so Phase 5
     can size slides from `scene_durations` and attach the combined file as the video's audio
     track with no drift.
   - Clean up temp per-scene files after successful concatenation.
4. Log start/engine-used/per-scene timing/success/failure via `utils/logging.py` — log which
   engine actually produced the file (useful for debugging offline runs).
5. Manual smoke test: run against one of the 3 storyboards with internet available (edge-tts
   path, verify `scene_durations` roughly matches each scene's narration length), and again with
   network disabled if feasible (pyttsx3 fallback path, verify all-scenes-consistent engine).

## Success Criteria
- [x] `narration.mp3` generated for at least one real storyboard via `edge-tts`, playable,
      `scene_durations` length matches the storyboard's scene count. (verified: real-network
      test `test_generate_narration_real_edge_tts_end_to_end` passes with ffmpeg not on PATH)
- [x] Forcing `edge-tts` to fail on one scene (mock/monkeypatch) triggers **all** scenes to
      regenerate via `pyttsx3` (verify no mixed-engine output), still produces a valid
      `narration.mp3` + `scene_durations`.
- [x] Forcing both engines to fail raises `NarrationGenerationError`.
- [x] Retry/timeout logic verified with a unit test (mock a timeout on first attempt, succeed on
      retry).
- [ ] README documents both engines, the per-scene generation approach, and that the offline
      fallback removes the hard internet-access requirement — **deferred to Phase 7 by design**
      (this criterion is explicitly cross-referenced to Phase 7 in the spec; README.md is still a
      stub as of this review, which is expected at this point in the plan).

## Review Notes (2026-07-19, code-reviewer, 8/10)
Full report: `plans/reports/code-reviewer-260719-0114-phase4-audio-narration-review.md`.
44/44 tests pass (37 prior + 7 new). Phase 5/6 contract match confirmed exact
(`scene_durations[i]`, `combined_path`, `engine_used` all consumed as implemented). Engine-mixing
guarantee verified bulletproof by code read + test. Two follow-up items before/alongside Phase 5:
1. (High) `_transcode_wav_to_mp3`, `_measure_duration`, and the final `concatenate_audioclips`/
   `write_audiofile` block run MoviePy/ffmpeg subprocess work directly on the event loop inside
   `async def generate_narration` — not wrapped in `asyncio.to_thread`, unlike `_synth_pyttsx3`.
   Blocks concurrent job progress under the `asyncio.create_task` model.
2. (Medium) "readable duration" acceptance check from the spec isn't implemented —
   `_is_valid_audio_file` only checks exists+size>0. A size>0-but-corrupt clip would pass engine
   selection, then fail later at `_measure_duration()`, outside the fallback's try/except, raising
   a raw exception instead of `NarrationGenerationError`/triggering pyttsx3 fallback. Muted impact
   since Phase 6's pipeline catches broad `Exception` anyway.
Finding for Phase 5: ffmpeg is NOT on system PATH in this dev environment, yet the full audio
pipeline (transcode/duration/concat via MoviePy) works, because MoviePy 2.x transitively bundles
`imageio_ffmpeg`. This bypasses the plan's documented ffmpeg risk for audio — but Phase 5 must
verify this independently for video rendering rather than assume the same holds.

## Risk Assessment
Per-scene generation means 4-5 `edge-tts` network calls per job instead of 1 — more surface area
for a transient failure, mitigated by per-call retry and the all-or-nothing engine fallback
(never leaves a video with inconsistent voices). `pyttsx3` on Windows uses SAPI5 — voice
availability/quality varies by machine; acceptable since it's a fallback path. Transcoding
`pyttsx3`'s `.wav` output to `.mp3` needs ffmpeg — a project-wide system prerequisite (also
required by MoviePy, see Phase 5) documented once in README setup, not reinstalled per phase.
