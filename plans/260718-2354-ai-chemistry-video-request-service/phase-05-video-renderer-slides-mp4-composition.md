---
phase: 5
title: "Video Renderer (Slides + MP4 Composition)"
status: pending
priority: P1
effort: "4-5h"
dependencies: [4]
---

# Phase 5: Video Renderer (Slides + MP4 Composition)

## Overview
Render each storyboard scene as a Pillow slide image, then compose slides + narration audio into
a single MP4 with MoviePy 2.x, saved as `artifacts/{job_id}/video.mp4`. Slide durations come from
Phase 4's per-scene `scene_durations`, not an even split. Includes typography/QA rules and an
artifact validation function called before a job is marked completed. Maps to master prompt §13,
§18 Step 6. <!-- Updated: Validation Session 2 - MoviePy 2.x API (PLAN_REVIEW #4), per-scene
timing (PLAN_REVIEW #8), typography/QA (PLAN_REVIEW #14), artifact validation (PLAN_REVIEW #12),
electron-transfer visual (PLAN_REVIEW #13), to_thread contract (PLAN_REVIEW #1) -->

## Requirements
- Functional: `render_video(job_id, storyboard, narration: NarrationResult) -> Path` produces a
  ~30-70s MP4, 4-5 scenes each sized to its own `narration.scene_durations[i]`, readable text,
  basic diagrams matching `visual_type`.
- Functional: support all 5 visual types: `title`, `ph_scale`, `atom_sharing`,
  `comparison_table`, `summary`. `atom_sharing`/`comparison_table` scenes for
  `ionic_vs_covalent` must render an explicit electron-transfer arrow, not just table text
  (PLAN_REVIEW #13 — matches the storyboard content fix in Phase 3).
- Functional: `validate_video(path: Path) -> None` — raises `VideoValidationError` if the file
  doesn't exist, size is 0, duration is outside 30-70s, or it has no audio/video stream. Called
  by Phase 6 before marking a job `completed` (PLAN_REVIEW #12).
- Non-functional: MoviePy requires ffmpeg on PATH. Confirmed NOT installed in this dev
  environment as of plan validation — user chose manual system install over bundling
  `imageio-ffmpeg`. **Install ffmpeg before starting this phase's work.**
- Non-functional: **`render_video` is a synchronous, CPU/I/O-bound function. It must never be
  called directly inside an `async def` — callers (Phase 6's `pipeline_service.py`) MUST invoke
  it via `await asyncio.to_thread(render_video, ...)`.** This phase only needs to keep the
  function itself synchronous/blocking-safe (no internal `async`); the offload happens at the
  call site (PLAN_REVIEW #1).
- Non-functional: pin `moviepy>=2,<3` (from Phase 1) and use 2.x clip methods (`.with_audio()`,
  `.with_duration()`), not the 1.x `.set_audio()`/`.set_duration()` API (PLAN_REVIEW #4).

## Architecture
`video_renderer.py` has three layers: (1) slide image generation — one function per visual_type
drawing onto a Pillow `Image`/`ImageDraw` canvas; (2) MoviePy composition using 2.x's `.with_*`
API, sizing each `ImageClip` to its corresponding `scene_durations[i]`; (3) `validate_video()` —
a post-render check independent of the render path so Phase 6 can call it even if it imports
video files created elsewhere (e.g. re-validating on artifact-endpoint access).

## Related Code Files
- Create: `app/services/video_renderer.py`
- Create: `app/assets/fonts/` — bundle one open-license TTF (e.g. DejaVu Sans, already MoviePy's
  usual bundled fallback, or explicitly vendor a specific font) so text rendering doesn't depend
  on whatever fonts happen to be installed on the OS (PLAN_REVIEW #14).
- Create (optional): `app/services/render_templates/` if per-visual-type drawing logic gets long
  enough to warrant splitting from `video_renderer.py` (only if file exceeds ~250-300 lines —
  don't pre-split).
- Use (not create): `app/services/artifact_store.py` — `video_path(job_id)`, `slides_directory
  (job_id)`, atomic write for the final `video.mp4` (write to a temp path, `os.replace()` into
  place, so a crash mid-render never leaves a corrupt `video.mp4` that `validate_video()` — or
  worse, a stale successful check — would see).

## Implementation Steps
1. Install and confirm `ffmpeg` is on PATH (`ffmpeg -version`) before writing render code —
   this environment did not have it as of plan validation. Windows: download a static build
   (e.g. gyan.dev builds) and add to PATH, or `choco install ffmpeg` if Chocolatey is available.
   README setup section (Phase 7) must document this exact step.
2. Typography rules (PLAN_REVIEW #14):
   - Load the bundled font explicitly (`ImageFont.truetype(FONT_PATH, size)`) — never rely on
     `ImageFont.load_default()` for scene text (too small/unreadable at video resolution).
   - Wrap text to the slide's usable pixel width using `draw.textbbox(...)` to measure actual
     rendered width per line, not a naive character-count heuristic.
   - Minimum font sizes: heading ≥ 40px, body ≥ 28px at 1280x720; minimum 60px margin on all
     sides; text color must have strong contrast against its background (e.g. dark text on
     light background or vice versa, no low-contrast pairings).
3. `video_renderer.py`: `_draw_slide(scene: Scene, size=(1280,720)) -> Image` dispatching on
   `scene.visual_type`:
   - `title`: centered heading + subtitle text.
   - `ph_scale`: horizontal 0-14 bar, acidic(red)/neutral(green)/basic(blue) zones, labels.
   - `atom_sharing`: two circles ("atoms") with a shared electron-pair marker between them; for
     `ionic_vs_covalent` scenes, additionally draw a directional arrow between two atom/ion
     symbols labeled to represent electron transfer (e.g. Na → Cl⁻), visually distinct from the
     shared-pair marker used for covalent scenes (PLAN_REVIEW #13).
   - `comparison_table`: simple 2-column table (ionic vs covalent) drawn with grid lines + text.
   - `summary`: bullet list of `scene.visual_text` lines.
   - Always render `scene.heading` as a title bar, apply the typography rules from step 2.
4. `_save_slide_images(job_id, storyboard) -> list[Path]` — one PNG per scene into
   `artifact_store.slides_directory(job_id)`.
5. `render_video(job_id, storyboard, narration: NarrationResult) -> Path`: build one `ImageClip`
   per slide with `.with_duration(narration.scene_durations[i])` (exact per-scene sync,
   PLAN_REVIEW #8), concatenate via `concatenate_videoclips`, attach
   `.with_audio(AudioFileClip(narration.combined_path))`, write to a temp path via
   `.write_videofile(temp_path)`, then `artifact_store.atomic_write`-style `os.replace()` into
   `artifact_store.video_path(job_id)`.
6. `validate_video(path: Path) -> None` (PLAN_REVIEW #12):
   - Raise if `not path.exists()` or `path.stat().st_size == 0`.
   - Open with `VideoFileClip(path)` (or `ffprobe` subprocess for a lighter check); raise if
     `duration` is outside `[30, 70]` seconds.
   - Raise if the clip has no audio track (`clip.audio is None`) or no video track.
   - Close the clip handle after checking (avoid file-handle leaks across job runs).
7. QA render step: generate a "contact sheet" (grid image of all slide PNGs for one job) via
   Pillow, for manual visual QA — run this for **all 3** required concepts, not just one
   (PLAN_REVIEW #14), before considering this phase done.
8. Log render start/duration/success/failure.

## Success Criteria
- [ ] `video.mp4` produced for at least one concept, plays, duration matches `sum(scene_durations)`.
- [ ] All 5 visual types render distinct, readable slides (spot-checked visually via contact
      sheet, all 3 concepts — not just one smoke test).
- [ ] `ionic_vs_covalent` renders a visibly distinct electron-transfer arrow, not just a table.
- [ ] Video includes narration audio (not silent), audio duration matches video duration (no
      drift, since both derive from the same `scene_durations`).
- [ ] `validate_video()` correctly raises on a truncated/zero-byte file, a too-short/too-long
      duration, and a video with no audio track (test with deliberately broken fixtures).
- [ ] Output path matches `artifacts/{job_id}/video.mp4` exactly, written atomically.
- [ ] No `.set_audio()`/`.set_duration()` (1.x API) calls anywhere in this file — 2.x `.with_*`
      only.

## Risk Assessment
Biggest risk is MoviePy/ffmpeg environment setup on Windows — verify early in this phase, not at
the end. MoviePy 2.x's `.with_*` rename is a real breaking-change surface — grep the finished
file for `.set_` before considering the phase done. Keep diagrams simple (basic shapes/text via
Pillow `ImageDraw`) — master prompt explicitly says "keep visuals simple, clean, and
educational"; the electron-transfer-arrow addition is a small, targeted content-accuracy fix, not
a general invitation to add more elaborate graphics.
