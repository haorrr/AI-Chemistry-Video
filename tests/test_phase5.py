"""Phase 5 tests: slide rendering (render_templates) and MP4 composition +
validation (video_renderer).

Deliberate deviation from test_phase1-4.py: this file does NOT clean up
artifacts/{job_id}/ directories after each test. The user wants generated
Phase 5 videos/contact sheets left on disk under artifacts/ for manual visual
QA (artifacts/ is gitignored, so this doesn't pollute git). Each test uses a
fresh uuid4 job_id so tests never collide with each other on disk.

Some tests make real network calls (edge-tts) and real MoviePy/ffmpeg encodes
and are therefore multi-second — consistent with test_phase4.py's real-audio
tests.
"""

import asyncio
import uuid
from pathlib import Path

import numpy as np
import pytest
from moviepy import ImageClip
from PIL import Image

from app.models import NarrationResult, Scene, Storyboard
from app.services import artifact_store, render_templates, video_renderer
from app.services.audio_service import generate_narration
from app.services.render_templates import SLIDE_SIZE, draw_slide
from app.services.storyboard_generator import generate_storyboard
from app.services.video_renderer import (
    VideoValidationError,
    generate_contact_sheet,
    render_video,
    validate_video,
)


def _new_job_id() -> str:
    return str(uuid.uuid4())


def _make_storyboard(n_scenes: int = 3, visual_type: str = "summary") -> Storyboard:
    scenes = [
        Scene(
            heading=f"Scene {i}",
            visual_type=visual_type,
            visual_text=f"Point {i} one. Point {i} two.",
            narration=f"Narration text number {i}.",
        )
        for i in range(n_scenes)
    ]
    return Storyboard(title="Test Storyboard", concept="ph_scale", scenes=scenes)


def _make_silent_video(path: Path, duration: float, size=(320, 240), fps: int = 24) -> None:
    """Real MoviePy-generated, video-only (no audio) MP4 fixture."""
    frame = np.zeros((size[1], size[0], 3), dtype="uint8")
    frame[:] = (100, 150, 200)
    clip = ImageClip(frame).with_duration(duration)
    try:
        clip.write_videofile(str(path), fps=fps, codec="libx264", audio=False, logger=None)
    finally:
        clip.close()


# --- draw_slide: all 5 visual types render without raising ------------------


def test_draw_slide_title_renders_expected_size():
    scene = Scene(
        heading="Two Ways to Bond",
        visual_type="title",
        visual_text="Ionic vs Covalent Bonding",
        narration="Intro narration.",
    )
    img = draw_slide(scene)
    assert isinstance(img, Image.Image)
    assert img.size == SLIDE_SIZE


def test_draw_slide_ph_scale_renders_expected_size():
    scene = Scene(
        heading="The pH Scale",
        visual_type="ph_scale",
        visual_text="0 -- Acidic | 7 -- Neutral | 14 -- Basic",
        narration="pH scale narration.",
    )
    img = draw_slide(scene)
    assert isinstance(img, Image.Image)
    assert img.size == SLIDE_SIZE


def test_draw_slide_atom_sharing_renders_expected_size():
    scene = Scene(
        heading="Hydrogen Example",
        visual_type="atom_sharing",
        visual_text="H : H (one shared electron pair)",
        narration="Sharing narration.",
    )
    img = draw_slide(scene)
    assert isinstance(img, Image.Image)
    assert img.size == SLIDE_SIZE


def test_draw_slide_comparison_table_renders_expected_size():
    scene = Scene(
        heading="Transfer vs Share",
        visual_type="comparison_table",
        visual_text="Ionic: electron transfer | Covalent: electron sharing",
        narration="Comparison narration.",
    )
    img = draw_slide(scene)
    assert isinstance(img, Image.Image)
    assert img.size == SLIDE_SIZE


def test_draw_slide_summary_renders_expected_size():
    scene = Scene(
        heading="Examples",
        visual_type="summary",
        visual_text="Sodium chloride is ionic. Water is covalent.",
        narration="Summary narration.",
    )
    img = draw_slide(scene)
    assert isinstance(img, Image.Image)
    assert img.size == SLIDE_SIZE


# --- ionic_vs_covalent: electron-transfer vs shared-pair must be visually distinct


def test_atom_sharing_transfer_vs_share_produce_different_pixels():
    transfer_scene = Scene(
        heading="Electron Transfer (Ionic)",
        visual_type="atom_sharing",
        visual_text="Na -- electron transfer arrow --> Cl, forming Na+ and Cl-",
        narration="Transfer narration.",
    )
    share_scene = Scene(
        heading="Electron Sharing (Covalent)",
        visual_type="atom_sharing",
        visual_text="H : H (shared electron pair, no transfer)",
        narration="Sharing narration.",
    )

    # Sanity check the dispatch helper this distinction relies on.
    assert render_templates._is_transfer_scene(transfer_scene) is True
    assert render_templates._is_transfer_scene(share_scene) is False

    transfer_img = draw_slide(transfer_scene)
    share_img = draw_slide(share_scene)

    assert transfer_img.size == share_img.size == SLIDE_SIZE
    assert transfer_img.tobytes() != share_img.tobytes()


# --- render_video: real end-to-end concept ------------------------------------


def test_render_video_real_concept_produces_valid_mp4():
    job_id = _new_job_id()
    artifact_store.create_job_directory(job_id)
    storyboard = generate_storyboard("ph_scale")

    narration = asyncio.run(generate_narration(job_id, storyboard))

    result_path = render_video(job_id, storyboard, narration)

    assert result_path == artifact_store.video_path(job_id)
    assert result_path.is_file()
    assert result_path.stat().st_size > 0

    # Must not raise.
    validate_video(result_path)

    tmp_path = result_path.with_name(result_path.stem + ".tmp.mp4")
    assert not tmp_path.exists()

    from moviepy import VideoFileClip

    clip = VideoFileClip(str(result_path))
    try:
        expected_duration = sum(narration.scene_durations)
        assert abs(clip.duration - expected_duration) <= 1.0
    finally:
        clip.close()


# --- render_video: mismatched scene/duration counts --------------------------


def test_render_video_raises_value_error_on_scene_duration_mismatch():
    job_id = _new_job_id()
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)
    narration = NarrationResult(
        combined_path=artifact_store.audio_path(job_id),
        scene_durations=[10.0, 10.0],  # 2 durations for 3 scenes
        engine_used="edge-tts",
    )

    with pytest.raises(ValueError):
        render_video(job_id, storyboard, narration)


# --- validate_video: rejection cases -------------------------------------------


def test_validate_video_rejects_nonexistent_path(tmp_path):
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(VideoValidationError):
        validate_video(missing)


def test_validate_video_rejects_zero_byte_file(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(VideoValidationError):
        validate_video(empty)


def test_validate_video_rejects_corrupt_truncated_file(tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a real video file" * 50)
    with pytest.raises(VideoValidationError):
        validate_video(corrupt)


def test_validate_video_rejects_too_short_duration(tmp_path):
    short_video = tmp_path / "short.mp4"
    _make_silent_video(short_video, duration=5.0)
    with pytest.raises(VideoValidationError):
        validate_video(short_video)


def test_validate_video_rejects_no_audio_track(tmp_path):
    silent_video = tmp_path / "silent.mp4"
    _make_silent_video(silent_video, duration=35.0)
    with pytest.raises(VideoValidationError):
        validate_video(silent_video)


# --- generate_contact_sheet ----------------------------------------------------


def test_generate_contact_sheet_produces_valid_image(tmp_path):
    slide_paths = []
    for i in range(4):
        scene = Scene(
            heading=f"Slide {i}",
            visual_type="summary",
            visual_text=f"Bullet {i}.",
            narration="n/a",
        )
        img = draw_slide(scene)
        p = tmp_path / f"slide_{i:02d}.png"
        img.save(p)
        slide_paths.append(p)

    output_path = tmp_path / "contact_sheet.png"
    result = generate_contact_sheet(slide_paths, output_path, columns=2)

    assert result == output_path
    assert output_path.is_file()
    sheet = Image.open(output_path)
    assert sheet.size == (2 * 320, 2 * 180)  # 4 slides, 2 columns -> 2x2 grid


# --- MoviePy 2.x API check: no 1.x .set_audio()/.set_duration() leakage -----


def test_no_moviepy_1x_api_calls_in_render_source_files():
    video_renderer_src = Path(video_renderer.__file__).read_text(encoding="utf-8")
    render_templates_src = Path(render_templates.__file__).read_text(encoding="utf-8")

    for name, src in [
        ("video_renderer.py", video_renderer_src),
        ("render_templates.py", render_templates_src),
    ]:
        assert ".set_audio(" not in src, f"1.x MoviePy API leaked into {name}"
        assert ".set_duration(" not in src, f"1.x MoviePy API leaked into {name}"
