# Code Review: Phase 4 — Audio Narration Service

Date: 2026-07-19 | Reviewer: code-reviewer | Score: 8/10 | Status: not yet committed

## Scope
- Files reviewed: `app/models.py` (NarrationResult dataclass), `app/services/audio_service.py` (new),
  `tests/test_phase4.py` (new), `app/services/artifact_store.py` (read-only, contract check),
  Phase 5/6 plan files (contract-consumer check).
- Lines of code analyzed: ~155 (audio_service.py) + ~290 (test_phase4.py) + ~10 (models.py delta).
- Review focus: Phase 4 deliverable only, against `phase-04-audio-narration-service.md` Success
  Criteria, plan.md-level non-functional requirements, and Phase 5/6 contract compatibility.
- Updated plans: `plan.md` (phase 4 row -> Completed, reviewed), `phase-04-audio-narration-service.md`
  (status -> completed, criteria checked, Review Notes section added).

## Overall Assessment
Solid, spec-faithful implementation. All 44 tests pass (37 prior + 7 new), including one real
(unmocked) network call to edge-tts that proves the end-to-end pipeline works. The engine-mixing
guarantee (never mix edge-tts/pyttsx3 scenes in one video) is bulletproof by code inspection — a
partial edge-tts failure discards all edge-tts temp output and unconditionally regenerates every
scene via pyttsx3. `NarrationResult`'s shape and field names match exactly what Phase 5
(`narration.scene_durations[i]`, `narration.combined_path`) and Phase 6
(`narration.combined_path` as `audio_path`) already assume — no contract drift. Two real but
non-blocking gaps found (event-loop blocking on MoviePy calls, and an incomplete "readable
duration" accept-check); neither breaks functionality or the tested behavior.

## Critical Issues
None.

## High Priority Findings
1. **MoviePy/ffmpeg calls not offloaded via `asyncio.to_thread`.** `_transcode_wav_to_mp3`,
   `_measure_duration`, and the final `concatenate_audioclips(...)` / `combined.write_audiofile(...)`
   block in `generate_narration` (audio_service.py lines 71-84, 136-146) all run synchronously
   inside `async def` functions. `_synth_pyttsx3` is correctly wrapped
   (`await asyncio.to_thread(_synth_pyttsx3, ...)`, line 101) but the MoviePy transcode/measure/
   concat calls are not, even though they shell out to ffmpeg subprocesses and do real I/O. This
   contradicts the plan.md Success Criterion "No await-blocking calls (MoviePy render,
   `pyttsx3.runAndWait`) run directly on the event loop — all offloaded via `asyncio.to_thread`"
   (PLAN_REVIEW #1) in spirit, even though the phase-04 doc's literal wording only named
   `pyttsx3.runAndWait`. Under the plan's concurrency model (`asyncio.create_task` per job, no
   dedicated worker process), this will stall the event loop — and therefore all other concurrent
   jobs' progress and any concurrent HTTP handling — for the duration of every transcode/measure/
   concat call. Not caught by tests because tests run one job at a time via `asyncio.run(...)` with
   no concurrent event-loop activity to starve.
   - Fix: wrap the MoviePy-touching calls the same way pyttsx3 is wrapped, e.g.
     `await asyncio.to_thread(_transcode_wav_to_mp3, wav_path, mp3_path)`,
     `await asyncio.to_thread(_measure_duration, p)` (or gather), and move the final concat/write
     block into a small blocking helper called via `to_thread`.

## Medium Priority Improvements
2. **"Readable duration" accept-check not actually implemented.** Spec (phase-04 doc, requirement
   line 31-32): "before accepting any generated clip (either engine), verify the output file
   exists, has size > 0, and **has a readable duration**; delete partial/empty files before
   falling back." The implementation's `_is_valid_audio_file` (line 33-34) only checks
   `exists() and stat().st_size > 0` — it never attempts to open the clip and read `.duration`.
   Consequence: a scene clip that saves with nonzero size but corrupt/truncated audio content
   would pass the per-scene check, get accepted into `scene_paths`, and only fail later at
   `scene_durations = [_measure_duration(p) for p in scene_paths]` (line 136) — which sits
   **outside** the try/except that drives the pyttsx3 fallback. The intended resilience path
   (regenerate all scenes with the other engine) would not trigger for this specific failure mode;
   instead a raw exception propagates out of `generate_narration` (not wrapped as
   `NarrationGenerationError`). Impact is muted in practice: Phase 6's `run_job` catches broad
   `except Exception as e` and still marks the job `failed` with a message — so no job gets stuck
   or silently corrupted — but the "retry with the other engine" resilience the spec designed for
   this exact scenario is bypassed for corrupt-but-nonzero-size output.
   - Fix: in `_is_valid_audio_file` (or a new check called right after synth), attempt
     `AudioFileClip(path).duration` in a try/except and treat exceptions as invalid, mirroring the
     spec wording exactly.

## Low Priority Suggestions
3. Implementation Step 4 of the phase doc asks for logging of "start/engine-used/per-scene
   timing/success/failure." Current logging only covers success (`Narration generated via
   edge-tts...`) and failure-before-fallback; there's no explicit "start" log line or per-scene
   timing. Cosmetic/debuggability gap only, no functional impact.
4. `NarrationGenerationError` doesn't chain/reference which specific scene index failed in
   pyttsx3 (only the final message string) — fine for a prototype, would help debugging in a
   longer-running system.

## Positive Observations
- Engine-mixing guarantee is genuinely bulletproof: `_generate_via_pyttsx3` always regenerates
  **all** scenes from scratch (fresh loop over `storyboard.scenes`), fully replacing `scene_paths`
  rather than patching around the failure point — verified both by code read and by
  `test_generate_narration_falls_back_to_pyttsx3_for_all_scenes_on_partial_edge_failure`
  (asserts 3/3 pyttsx3 calls after edge-tts fails on scene index 1).
- `tmp_dir` cleanup (`shutil.rmtree(..., ignore_errors=True)` in a `finally`) runs on both success
  and failure paths — verified by dedicated tests for each.
- Retry/backoff (`_EDGE_TTS_MAX_ATTEMPTS=3`, `_RETRY_BACKOFF_SECONDS=(1.0, 2.0)`) matches spec
  exactly (1 initial + 2 retries, no trailing sleep after the final attempt).
- `NarrationResult` dataclass field names/types match Phase 5/6 consumers exactly — verified by
  grep against both phase files: `narration.scene_durations[i]` (Phase 5, sizes each `ImageClip`),
  `narration.combined_path` (Phase 5 audio track + Phase 6's `Job.audio_path`), `engine_used`
  (logged, not consumed downstream yet). No contract drift.
- requirements.txt already pins `edge-tts`, `pyttsx3`, `moviepy>=2,<3` — nothing missing for this
  phase.

## Finding for Phase 5 (not a Phase 4 defect — flagging per review instructions)
`ffmpeg` is confirmed **not** on system PATH in this dev environment
(`where ffmpeg` → not found), yet the entire audio pipeline — `AudioFileClip`, `write_audiofile`,
`concatenate_audioclips` — works, including the real-network edge-tts test
(`test_generate_narration_real_edge_tts_end_to_end`, unmocked, passed). Root cause: MoviePy 2.x
depends on `imageio_ffmpeg`, which bundles its own ffmpeg binary
(`D:\Desktop\AI-Chemistry-Video\.venv\lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe`,
confirmed via `imageio_ffmpeg.get_ffmpeg_exe()`), and MoviePy transparently falls back to it when
no system ffmpeg is found. This bypasses the plan's documented Risk ("ffmpeg NOT on PATH, user
chose manual system install") **for audio purposes**. Video rendering (Phase 5) may work the same
way since it also goes through MoviePy — but Phase 5 must verify this itself (different codec
requirements, `ImageClip` handling, etc. could behave differently); this review does not assume
it does.

## Recommended Actions
1. (High) Wrap `_transcode_wav_to_mp3`, `_measure_duration`, and the final concat/write block in
   `asyncio.to_thread` inside `generate_narration` before Phase 6 wires concurrent job execution —
   otherwise concurrent jobs will serialize on audio processing despite the `asyncio.create_task`
   design intent.
2. (Medium) Add a real "readable duration" check (open + read `.duration`, catch exceptions) to
   the per-clip accept gate, matching the spec's literal requirement, so the pyttsx3 fallback
   triggers on corrupt-but-nonzero-size output too.
3. (Low) Optional: add a "start" log line and per-scene timing to match Implementation Step 4
   fully. Not blocking.
4. No action needed now: README documentation criterion is correctly deferred to Phase 7 per the
   phase-04 spec's own cross-reference — not a Phase 4 gap.

## Metrics
- Type Coverage: not formally measured (no mypy config in repo); manual read shows consistent
  type hints throughout new code.
- Test Coverage: 7/7 new Phase 4 tests pass; all Success Criteria have a corresponding test except
  the README criterion (explicitly deferred to Phase 7).
- Linting: no ruff/flake8/mypy config present in repo; `py_compile` clean on all 3 touched files.
- Full suite: 44/44 passed, 1 pre-existing unrelated deprecation warning (`httpx`/starlette
  TestClient), 5.63s.

## Regression / Stop-Gate Check
No stop-and-ask-user gate triggered. No regressions (all 37 prior tests still pass unchanged), no
public-contract break (Phase 5/6's exact field usages verified against the real implementation),
no engine-mixing bug found. The two findings above (High: event-loop blocking; Medium: duration
accept-check) are real but don't break current tested behavior or downstream contracts — safe to
proceed to Phase 5, with a recommendation to fix #1 before/while wiring Phase 6's concurrency.

## Unresolved Questions
- None for Phase 4 itself. Open item to carry into Phase 5's own review: confirm whether Phase 5's
  video rendering also works without system ffmpeg via `imageio_ffmpeg`, or whether it genuinely
  needs the system install the plan's Risk section documents.
