"""Per-scene narration audio: edge-tts primary, pyttsx3 offline fallback.

All-or-nothing engine choice per job (never mixes voices within one video).
Uses MoviePy for transcode/duration/concat — MoviePy 2.x bundles its own
ffmpeg binary via imageio_ffmpeg, so no system ffmpeg on PATH is required
for this module specifically (video rendering in Phase 5 still needs it).
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Callable

import edge_tts
import pyttsx3
from moviepy import AudioFileClip, concatenate_audioclips

from app.models import NarrationResult, Storyboard
from app.services import artifact_store
from app.utils.logging import get_logger

logger = get_logger(__name__)

_EDGE_TTS_VOICE = "en-US-AriaNeural"
_EDGE_TTS_TIMEOUT_SECONDS = 15.0
_EDGE_TTS_MAX_ATTEMPTS = 3  # 1 initial + 2 retries
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)

# Soft timeouts for blocking work run via asyncio.to_thread. NOTE: asyncio.wait_for
# only stops *awaiting* — it cannot forcibly kill the underlying OS thread. If
# pyttsx3.runAndWait() hangs (e.g. a SAPI driver issue), the orphaned thread keeps
# running in the background after this raises TimeoutError. This bounds how long a
# job appears "stuck" from the caller's perspective; it does not guarantee the
# engine actually stops. A hard kill would require subprocess isolation, which is
# out of scope for this prototype.
_PYTTSX3_TIMEOUT_SECONDS = 30.0
_TRANSCODE_TIMEOUT_SECONDS = 30.0
_CONCAT_TIMEOUT_SECONDS = 60.0


class NarrationGenerationError(Exception):
    pass


async def _run_blocking(func: Callable, *args, timeout: float):
    return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=timeout)


def _is_valid_audio_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _validate_audio_output(path: Path) -> float:
    """Blocking. Verifies the file exists, is non-empty, and has a readable,
    positive duration. Returns the duration on success; raises RuntimeError
    otherwise. Call via _run_blocking/asyncio.to_thread — never directly in
    an async def."""
    if not _is_valid_audio_file(path):
        raise RuntimeError(f"Audio output missing or empty: {path}")
    clip = None
    try:
        clip = AudioFileClip(str(path))
        duration = clip.duration
    except Exception as e:
        raise RuntimeError(f"Audio output unreadable/corrupt: {path} ({e})") from e
    finally:
        if clip is not None:
            clip.close()
    if not duration or duration <= 0:
        raise RuntimeError(f"Audio output has invalid duration ({duration}): {path}")
    return duration


async def _synth_edge_tts(text: str, out_path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(_EDGE_TTS_MAX_ATTEMPTS):
        try:
            if out_path.exists():
                out_path.unlink()
            communicate = edge_tts.Communicate(text, voice=_EDGE_TTS_VOICE)
            await asyncio.wait_for(
                communicate.save(str(out_path)), timeout=_EDGE_TTS_TIMEOUT_SECONDS
            )
            # Corrupt-but-nonempty output must be treated as a failure here (not
            # discovered later during final duration measurement), so it correctly
            # triggers this function's own retry loop and, if retries exhaust, the
            # caller's all-or-nothing pyttsx3 fallback.
            await _run_blocking(
                _validate_audio_output, out_path, timeout=_TRANSCODE_TIMEOUT_SECONDS
            )
            return
        except Exception as e:
            last_error = e
            if out_path.exists():
                out_path.unlink()
            if attempt < _EDGE_TTS_MAX_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    raise RuntimeError(f"edge-tts failed after retries: {last_error}") from last_error


def _synth_pyttsx3(text: str, out_path_wav: Path) -> None:
    """Blocking. Must be called via _run_blocking/asyncio.to_thread — never
    directly in async def."""
    engine = pyttsx3.init()
    try:
        engine.save_to_file(text, str(out_path_wav))
        engine.runAndWait()
    finally:
        engine.stop()
    if not _is_valid_audio_file(out_path_wav):
        raise RuntimeError("pyttsx3 produced an empty or missing file")


def _transcode_wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    """Blocking (ffmpeg subprocess via MoviePy). Call via asyncio.to_thread."""
    clip = AudioFileClip(str(wav_path))
    try:
        clip.write_audiofile(str(mp3_path), logger=None)
    finally:
        clip.close()


def _measure_durations(paths: list[Path]) -> list[float]:
    """Blocking. Call via asyncio.to_thread."""
    durations = []
    for p in paths:
        clip = AudioFileClip(str(p))
        try:
            durations.append(clip.duration)
        finally:
            clip.close()
    return durations


def _concatenate_and_write(scene_paths: list[Path], combined_path: Path) -> None:
    """Blocking (ffmpeg subprocess via MoviePy). Call via asyncio.to_thread.

    Writes to a temp file in the same directory, validates the result, then
    atomically renames into place — a crash/failure mid-encode never leaves a
    partial/corrupt narration.mp3 at the final path.
    """
    clips: list[AudioFileClip] = []
    combined = None
    # Keep the real ".mp3" extension (not e.g. ".mp3.tmp") — MoviePy infers the
    # output codec from the file extension and fails on an unrecognized one.
    tmp_path = combined_path.with_name(combined_path.stem + ".tmp.mp3")
    try:
        for p in scene_paths:
            clips.append(AudioFileClip(str(p)))
        combined = concatenate_audioclips(clips)
        combined.write_audiofile(str(tmp_path), logger=None)
    finally:
        if combined is not None:
            combined.close()
        for c in clips:
            c.close()

    _validate_audio_output(tmp_path)
    os.replace(tmp_path, combined_path)


async def _generate_via_edge_tts(scenes, tmp_dir: Path) -> list[Path]:
    scene_paths: list[Path] = []
    for i, scene in enumerate(scenes):
        out_path = tmp_dir / f"scene_{i:02d}.mp3"
        await _synth_edge_tts(scene.narration, out_path)
        scene_paths.append(out_path)
    return scene_paths


async def _generate_via_pyttsx3(scenes, tmp_dir: Path) -> list[Path]:
    scene_paths: list[Path] = []
    for i, scene in enumerate(scenes):
        wav_path = tmp_dir / f"scene_{i:02d}.wav"
        mp3_path = tmp_dir / f"scene_{i:02d}.mp3"
        await _run_blocking(
            _synth_pyttsx3, scene.narration, wav_path, timeout=_PYTTSX3_TIMEOUT_SECONDS
        )
        await _run_blocking(
            _transcode_wav_to_mp3, wav_path, mp3_path, timeout=_TRANSCODE_TIMEOUT_SECONDS
        )
        wav_path.unlink(missing_ok=True)
        # Corrupt pyttsx3/transcode output is a real, unrecoverable engine failure
        # (no third engine to fall back to) — surfaces as NarrationGenerationError.
        await _run_blocking(
            _validate_audio_output, mp3_path, timeout=_TRANSCODE_TIMEOUT_SECONDS
        )
        scene_paths.append(mp3_path)
    return scene_paths


def _discard(paths: list[Path]) -> None:
    for p in paths:
        if p.exists():
            p.unlink()


async def generate_narration(job_id: str, storyboard: Storyboard) -> NarrationResult:
    tmp_dir = artifact_store.job_directory(job_id) / "_tmp_audio"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        try:
            scene_paths = await _generate_via_edge_tts(storyboard.scenes, tmp_dir)
            engine_used = "edge-tts"
            logger.info(f"Narration generated via edge-tts for job_id={job_id}")
        except Exception as e:
            logger.error(
                f"edge-tts failed for job_id={job_id}, falling back to pyttsx3: {e}"
            )
            _discard(list(tmp_dir.glob("scene_*")))
            try:
                scene_paths = await _generate_via_pyttsx3(storyboard.scenes, tmp_dir)
                engine_used = "pyttsx3"
                logger.info(f"Narration generated via pyttsx3 fallback for job_id={job_id}")
            except Exception as fallback_error:
                raise NarrationGenerationError(
                    f"Both edge-tts and pyttsx3 failed for job_id={job_id}: {fallback_error}"
                ) from fallback_error

        scene_durations = await _run_blocking(
            _measure_durations, scene_paths, timeout=_CONCAT_TIMEOUT_SECONDS
        )

        combined_path = artifact_store.audio_path(job_id)
        await _run_blocking(
            _concatenate_and_write,
            scene_paths,
            combined_path,
            timeout=_CONCAT_TIMEOUT_SECONDS,
        )

        return NarrationResult(
            combined_path=combined_path,
            scene_durations=scene_durations,
            engine_used=engine_used,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
