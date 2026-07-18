"""Phase 4 tests: per-scene narration audio generation (audio_service).

Most tests mock `_synth_edge_tts` / `_synth_pyttsx3` so the suite stays fast and
deterministic (no network, no multi-second real synthesis). Real, valid tiny audio
content (generated once via real pyttsx3 at session scope) is written by the mocks
so duration measurement and MoviePy concatenation exercise real file I/O, not
empty stubs. One test (`test_generate_narration_real_edge_tts_end_to_end`) makes
real network calls to edge-tts to prove the happy path works end-to-end.

`generate_narration` is async with no running event loop in these tests, so it's
driven via `asyncio.run(...)` (no pytest-asyncio dependency in this project).

Any artifacts/{job_id}/ directories created during a test are removed at teardown
so the repo's artifacts/ dir stays clean (mirrors test_phase2/3.py).
"""

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from app.config import ARTIFACTS_DIR
from app.models import NarrationResult, Scene, Storyboard
from app.services import artifact_store, audio_service
from app.services.audio_service import NarrationGenerationError, generate_narration


@pytest.fixture(autouse=True)
def cleanup_artifacts():
    yield
    for entry in ARTIFACTS_DIR.iterdir():
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink()


def _make_storyboard(n_scenes: int = 3) -> Storyboard:
    scenes = [
        Scene(
            heading=f"Scene {i}",
            visual_type="summary",
            visual_text=f"text {i}",
            narration=f"Narration text number {i}.",
        )
        for i in range(n_scenes)
    ]
    return Storyboard(title="Test Storyboard", concept="ph_scale", scenes=scenes)


@pytest.fixture(scope="session")
def tiny_audio_fixtures(tmp_path_factory):
    """Real, valid tiny wav+mp3 bytes generated once via real pyttsx3 synthesis.

    Reused by mocked `_synth_edge_tts`/`_synth_pyttsx3` across tests so duration
    measurement and concatenation operate on real audio files without paying the
    cost of real synthesis (or a network call) per scene per test.
    """
    tmp_dir = tmp_path_factory.mktemp("tiny_audio_fixture")
    wav_path = tmp_dir / "tiny.wav"
    mp3_path = tmp_dir / "tiny.mp3"
    audio_service._synth_pyttsx3("Hi.", wav_path)
    audio_service._transcode_wav_to_mp3(wav_path, mp3_path)
    return {"wav": wav_path.read_bytes(), "mp3": mp3_path.read_bytes()}


# --- mock helpers ------------------------------------------------------------


def _patch_edge_tts_always_succeeds(monkeypatch, mp3_bytes: bytes) -> list:
    calls: list = []

    async def fake(text: str, out_path: Path) -> None:
        calls.append((text, out_path))
        Path(out_path).write_bytes(mp3_bytes)

    monkeypatch.setattr(audio_service, "_synth_edge_tts", fake)
    return calls


def _patch_edge_tts_fails_on_index(monkeypatch, mp3_bytes: bytes, fail_index: int) -> list:
    calls: list = []

    async def fake(text: str, out_path: Path) -> None:
        idx = len(calls)
        calls.append((text, out_path))
        if idx == fail_index:
            raise RuntimeError("simulated edge-tts failure")
        Path(out_path).write_bytes(mp3_bytes)

    monkeypatch.setattr(audio_service, "_synth_edge_tts", fake)
    return calls


def _patch_edge_tts_always_fails(monkeypatch) -> list:
    calls: list = []

    async def fake(text: str, out_path: Path) -> None:
        calls.append((text, out_path))
        raise RuntimeError("simulated edge-tts failure")

    monkeypatch.setattr(audio_service, "_synth_edge_tts", fake)
    return calls


def _patch_pyttsx3_always_succeeds(monkeypatch, wav_bytes: bytes) -> list:
    calls: list = []

    def fake(text: str, out_path_wav: Path) -> None:
        calls.append(text)
        Path(out_path_wav).write_bytes(wav_bytes)

    monkeypatch.setattr(audio_service, "_synth_pyttsx3", fake)
    return calls


def _patch_pyttsx3_always_fails(monkeypatch) -> list:
    calls: list = []

    def fake(text: str, out_path_wav: Path) -> None:
        calls.append(text)
        raise RuntimeError("simulated pyttsx3 failure")

    monkeypatch.setattr(audio_service, "_synth_pyttsx3", fake)
    return calls


# --- happy path (mocked edge-tts) --------------------------------------------


def test_generate_narration_happy_path_returns_valid_result(monkeypatch, tiny_audio_fixtures):
    _patch_edge_tts_always_succeeds(monkeypatch, tiny_audio_fixtures["mp3"])

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(4)

    result = asyncio.run(generate_narration(job_id, storyboard))

    assert isinstance(result, NarrationResult)
    assert result.engine_used == "edge-tts"
    assert len(result.scene_durations) == 4
    assert all(d > 0 for d in result.scene_durations)
    assert result.combined_path == artifact_store.audio_path(job_id)
    assert result.combined_path.is_file()
    assert result.combined_path.stat().st_size > 0


# --- one real, unmocked edge-tts network call proving the real pipeline works ----


def test_generate_narration_real_edge_tts_end_to_end():
    """Real network call to edge-tts (no mocking) — proves the actual TTS + MoviePy
    concatenation pipeline produces a valid narration.mp3 with correct scene count.
    Storyboard requires >=3 scenes (model validation), so this can't be a true
    single-scene test; short narration text keeps it fast regardless.
    """
    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    result = asyncio.run(generate_narration(job_id, storyboard))

    assert result.engine_used == "edge-tts"
    assert len(result.scene_durations) == 3
    assert all(d > 0 for d in result.scene_durations)
    assert result.combined_path.is_file()
    assert result.combined_path.stat().st_size > 0


# --- fallback: any edge-tts scene failure -> ALL scenes redone via pyttsx3 ------


def test_generate_narration_falls_back_to_pyttsx3_for_all_scenes_on_partial_edge_failure(
    monkeypatch, tiny_audio_fixtures
):
    edge_calls = _patch_edge_tts_fails_on_index(
        monkeypatch, tiny_audio_fixtures["mp3"], fail_index=1
    )
    pyttsx3_calls = _patch_pyttsx3_always_succeeds(monkeypatch, tiny_audio_fixtures["wav"])

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    result = asyncio.run(generate_narration(job_id, storyboard))

    # edge-tts attempted scene 0 (succeeded) then scene 1 (failed) and stopped.
    assert len(edge_calls) == 2
    # ALL 3 scenes were regenerated via pyttsx3 (no mixed-engine output).
    assert len(pyttsx3_calls) == 3
    assert result.engine_used == "pyttsx3"
    assert len(result.scene_durations) == 3
    assert all(d > 0 for d in result.scene_durations)
    assert result.combined_path.is_file()
    assert result.combined_path.stat().st_size > 0


# --- both engines fail -> NarrationGenerationError ------------------------------


def test_generate_narration_raises_when_both_engines_fail(monkeypatch):
    _patch_edge_tts_always_fails(monkeypatch)
    _patch_pyttsx3_always_fails(monkeypatch)

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    with pytest.raises(NarrationGenerationError):
        asyncio.run(generate_narration(job_id, storyboard))

    # No partial/leftover combined file from the failed attempt.
    assert not artifact_store.audio_path(job_id).exists()


# --- retry logic: edge-tts fails once, succeeds on retry, no fallback triggered --


def test_generate_narration_edge_tts_retry_succeeds_without_falling_back(
    monkeypatch, tiny_audio_fixtures
):
    # Speed up the retry backoff for the test.
    monkeypatch.setattr(audio_service, "_RETRY_BACKOFF_SECONDS", (0.01, 0.01))

    attempts = {"count": 0}

    class FlakyCommunicate:
        def __init__(self, text: str, voice: str | None = None, **kwargs) -> None:
            pass

        async def save(self, out_path) -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("simulated transient network failure")
            Path(out_path).write_bytes(tiny_audio_fixtures["mp3"])

    monkeypatch.setattr(audio_service.edge_tts, "Communicate", FlakyCommunicate)
    # If retry didn't work and the outer fallback were incorrectly triggered,
    # this would raise and fail the test loudly instead of silently passing.
    pyttsx3_calls = _patch_pyttsx3_always_fails(monkeypatch)

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    result = asyncio.run(generate_narration(job_id, storyboard))

    # Only the very first attempt (scene 0's first try) fails; every other attempt
    # (scene 0's retry + scenes 1 and 2's first tries) succeeds: n_scenes + 1 calls.
    assert attempts["count"] == len(storyboard.scenes) + 1
    assert result.engine_used == "edge-tts"
    assert len(pyttsx3_calls) == 0  # fallback never triggered
    assert len(result.scene_durations) == 3


# --- _tmp_audio cleanup ---------------------------------------------------------


def test_tmp_audio_dir_removed_after_success(monkeypatch, tiny_audio_fixtures):
    _patch_edge_tts_always_succeeds(monkeypatch, tiny_audio_fixtures["mp3"])

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    asyncio.run(generate_narration(job_id, storyboard))

    tmp_dir = artifact_store.job_directory(job_id) / "_tmp_audio"
    assert not tmp_dir.exists()


def test_tmp_audio_dir_removed_after_failure(monkeypatch):
    _patch_edge_tts_always_fails(monkeypatch)
    _patch_pyttsx3_always_fails(monkeypatch)

    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)
    storyboard = _make_storyboard(3)

    with pytest.raises(NarrationGenerationError):
        asyncio.run(generate_narration(job_id, storyboard))

    tmp_dir = artifact_store.job_directory(job_id) / "_tmp_audio"
    assert not tmp_dir.exists()
