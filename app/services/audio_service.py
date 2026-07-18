"""Per-scene narration audio: edge-tts primary, pyttsx3 offline fallback.

All-or-nothing engine choice per job (never mixes voices within one video).
Uses MoviePy for transcode/duration/concat — MoviePy 2.x bundles its own
ffmpeg binary via imageio_ffmpeg, so no system ffmpeg on PATH is required
for this module specifically (video rendering in Phase 5 still needs it).
"""

import asyncio
import shutil
from pathlib import Path

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


class NarrationGenerationError(Exception):
    pass


def _is_valid_audio_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


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
            if _is_valid_audio_file(out_path):
                return
            raise RuntimeError("edge-tts produced an empty or missing file")
        except Exception as e:
            last_error = e
            if out_path.exists():
                out_path.unlink()
            if attempt < _EDGE_TTS_MAX_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    raise RuntimeError(f"edge-tts failed after retries: {last_error}") from last_error


def _synth_pyttsx3(text: str, out_path_wav: Path) -> None:
    """Blocking. Must be called via asyncio.to_thread — never directly in async def."""
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


def _measure_duration(path: Path) -> float:
    """Blocking. Call via asyncio.to_thread."""
    clip = AudioFileClip(str(path))
    try:
        return clip.duration
    finally:
        clip.close()


def _measure_durations(paths: list[Path]) -> list[float]:
    """Blocking. Call via asyncio.to_thread."""
    return [_measure_duration(p) for p in paths]


def _concatenate_and_write(scene_paths: list[Path], combined_path: Path) -> None:
    """Blocking (ffmpeg subprocess via MoviePy). Call via asyncio.to_thread."""
    clips = [AudioFileClip(str(p)) for p in scene_paths]
    try:
        combined = concatenate_audioclips(clips)
        combined.write_audiofile(str(combined_path), logger=None)
    finally:
        for c in clips:
            c.close()


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
        await asyncio.to_thread(_synth_pyttsx3, scene.narration, wav_path)
        await asyncio.to_thread(_transcode_wav_to_mp3, wav_path, mp3_path)
        wav_path.unlink(missing_ok=True)
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

        scene_durations = await asyncio.to_thread(_measure_durations, scene_paths)

        combined_path = artifact_store.audio_path(job_id)
        await asyncio.to_thread(_concatenate_and_write, scene_paths, combined_path)

        return NarrationResult(
            combined_path=combined_path,
            scene_durations=scene_durations,
            engine_used=engine_used,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
