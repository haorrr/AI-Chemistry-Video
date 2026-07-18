"""MoviePy composition (slides + narration audio -> MP4) and post-render
artifact validation. Slide drawing logic lives in render_templates.py.

render_video() is synchronous and CPU/I/O-bound. Callers (Phase 6's
pipeline_service.py) MUST invoke it via asyncio.to_thread — never directly
inside an async def.

Confirmed empirically (see Phase 4/5 review notes): MoviePy 2.x's imageio_ffmpeg
dependency bundles its own ffmpeg binary, so this module works without a system
ffmpeg install even though one isn't on PATH in this dev environment.
"""

import os
import time
from pathlib import Path

from moviepy import AudioFileClip, ImageClip, VideoFileClip, concatenate_videoclips
from moviepy.video.fx import FadeIn, FadeOut
from PIL import Image

from app.models import NarrationResult, Storyboard
from app.services import artifact_store, render_templates
from app.utils.logging import get_logger

logger = get_logger(__name__)

MIN_VIDEO_DURATION_SECONDS = 30.0
MAX_VIDEO_DURATION_SECONDS = 70.0

# Fade-through-black between every slide (plus at the very start/end) instead of
# hard cuts. A true crossfade dissolve (CrossFadeIn/Out + overlapping
# concatenate_videoclips(method="compose")) was measured at ~13x slower render
# time (compositing overhead, confirmed even on synthetic non-Pillow slides) for
# a cosmetic difference — not worth it for a cost-conscious prototype. FadeIn/
# FadeOut operate within each clip's own existing duration (fade to/from black),
# so concatenation stays in the fast default "chain" mode and total duration
# stays exactly sum(scene_durations) — no padding math, no audio-sync risk.
FADE_SECONDS = 0.3


def _build_slide_clips(slide_paths: list[Path], scene_durations: list[float]) -> list[ImageClip]:
    clips = []
    for i, (path, duration) in enumerate(zip(slide_paths, scene_durations)):
        clip = ImageClip(str(path)).with_duration(duration)
        clip = clip.with_effects([FadeIn(FADE_SECONDS), FadeOut(FADE_SECONDS)])
        clips.append(clip)
    return clips


class VideoValidationError(Exception):
    pass


def _save_slide_images(job_id: str, storyboard: Storyboard) -> list[Path]:
    slides_dir = artifact_store.slides_directory(job_id)
    slides_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, scene in enumerate(storyboard.scenes):
        img = render_templates.draw_slide(scene)
        path = slides_dir / f"slide_{i:02d}.png"
        img.save(path)
        paths.append(path)
    return paths


def generate_contact_sheet(slide_paths: list[Path], output_path: Path, columns: int = 3) -> Path:
    """Manual visual-QA utility: tiles slide PNGs into a single grid image.
    Not part of the runtime pipeline — used during development/demo QA."""
    thumb_w, thumb_h = 320, 180
    thumbs = [Image.open(p).resize((thumb_w, thumb_h)) for p in slide_paths]
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * thumb_h), color=(255, 255, 255))
    for i, t in enumerate(thumbs):
        x = (i % columns) * thumb_w
        y = (i // columns) * thumb_h
        sheet.paste(t, (x, y))
    sheet.save(output_path)
    return output_path


def render_video(job_id: str, storyboard: Storyboard, narration: NarrationResult) -> Path:
    """Synchronous, CPU/I/O-bound. Callers MUST invoke via asyncio.to_thread."""
    if len(storyboard.scenes) != len(narration.scene_durations):
        raise ValueError(
            f"scene count ({len(storyboard.scenes)}) != scene_durations count "
            f"({len(narration.scene_durations)})"
        )

    start = time.monotonic()
    logger.info(f"Render starting for job_id={job_id}, {len(storyboard.scenes)} scenes")

    slide_paths = _save_slide_images(job_id, storyboard)

    final_path = artifact_store.video_path(job_id)
    tmp_path = final_path.with_name(final_path.stem + ".tmp.mp4")

    opened_clips = []
    try:
        slide_clips = _build_slide_clips(slide_paths, narration.scene_durations)
        opened_clips.extend(slide_clips)

        combined_video = concatenate_videoclips(slide_clips)
        opened_clips.append(combined_video)

        audio_clip = AudioFileClip(str(narration.combined_path))
        opened_clips.append(audio_clip)

        final = combined_video.with_audio(audio_clip)
        opened_clips.append(final)

        # temp_audiofile_path must be set explicitly: MoviePy's default (cwd-relative,
        # named from just the target's basename) collides across concurrent renders,
        # since every job's temp video file shares the same basename ("video.tmp.mp4")
        # — only the parent directory differs. Confirmed via a real concurrent-render
        # run (run_demo.py, semaphore=2): both jobs wrote to the identical relative
        # temp audio path and raced on deleting it (Windows PermissionError).
        final.write_videofile(
            str(tmp_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile_path=str(tmp_path.parent),
            logger=None
        )
    finally:
        for c in opened_clips:
            try:
                c.close()
            except Exception:
                pass

    try:
        validate_video(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, final_path)

    elapsed = time.monotonic() - start
    logger.info(f"Render complete for job_id={job_id} in {elapsed:.1f}s -> {final_path}")
    return final_path


def validate_video(path: Path) -> None:
    """Raises VideoValidationError on any failure. Blocking — call via
    asyncio.to_thread if invoked from async code."""
    if not path.exists():
        raise VideoValidationError(f"Video file does not exist: {path}")
    if path.stat().st_size == 0:
        raise VideoValidationError(f"Video file is empty: {path}")

    clip = None
    try:
        clip = VideoFileClip(str(path))
        duration = clip.duration
        if duration is None or not (
            MIN_VIDEO_DURATION_SECONDS <= duration <= MAX_VIDEO_DURATION_SECONDS
        ):
            raise VideoValidationError(
                f"Video duration {duration}s outside allowed range "
                f"[{MIN_VIDEO_DURATION_SECONDS}, {MAX_VIDEO_DURATION_SECONDS}]: {path}"
            )
        if clip.audio is None:
            raise VideoValidationError(f"Video has no audio track: {path}")
        if clip.size is None:
            raise VideoValidationError(f"Video has no video stream: {path}")
    except VideoValidationError:
        raise
    except Exception as e:
        raise VideoValidationError(f"Video file unreadable/corrupt: {path} ({e})") from e
    finally:
        if clip is not None:
            clip.close()
