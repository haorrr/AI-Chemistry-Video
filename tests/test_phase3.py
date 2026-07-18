"""Phase 3 tests: Scene/Storyboard models and storyboard_generator service.

Any artifacts/{job_id}/ directories created during a test are removed at
teardown so the repo's artifacts/ dir stays clean (mirrors test_phase2.py).
"""

import json
import shutil
import uuid

import pytest
from pydantic import ValidationError

from app.config import ARTIFACTS_DIR
from app.models import Scene, Storyboard
from app.services import artifact_store, storyboard_generator
from app.services.storyboard_generator import (
    StoryboardGenerationError,
    generate_storyboard,
    save_storyboard,
)


@pytest.fixture(autouse=True)
def cleanup_artifacts():
    yield
    for entry in ARTIFACTS_DIR.iterdir():
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


# --- generate_storyboard: valid output for all 3 concepts --------------------


@pytest.mark.parametrize(
    "concept", ["ph_scale", "covalent_bonds", "ionic_vs_covalent"]
)
def test_generate_storyboard_returns_valid_storyboard_for_each_concept(concept):
    storyboard = generate_storyboard(concept)

    assert isinstance(storyboard, Storyboard)
    assert storyboard.concept == concept
    assert 3 <= len(storyboard.scenes) <= 6


def test_ph_scale_narration_mentions_logarithmic():
    storyboard = generate_storyboard("ph_scale")
    combined = " ".join(scene.narration for scene in storyboard.scenes).lower()
    assert "logarithmic" in combined


def test_ionic_vs_covalent_narration_mentions_transfer_and_share():
    storyboard = generate_storyboard("ionic_vs_covalent")
    combined = " ".join(scene.narration for scene in storyboard.scenes).lower()
    assert "transfer" in combined
    assert "share" in combined or "sharing" in combined


# --- Scene validation ----------------------------------------------------------


def test_scene_with_invalid_visual_type_raises_validation_error():
    with pytest.raises(ValidationError):
        Scene(
            heading="Bad",
            visual_type="not_a_real_type",
            visual_text="x",
            narration="x",
        )


# --- Storyboard validation ------------------------------------------------------


def _make_scene(n: int) -> Scene:
    return Scene(
        heading=f"Scene {n}",
        visual_type="summary",
        visual_text=f"text {n}",
        narration=f"narration {n}",
    )


def test_storyboard_with_unsupported_concept_raises_validation_error():
    with pytest.raises(ValidationError):
        Storyboard(
            title="Photosynthesis",
            concept="photosynthesis",
            scenes=[_make_scene(i) for i in range(3)],
        )


def test_storyboard_with_empty_title_raises_validation_error():
    with pytest.raises(ValidationError):
        Storyboard(
            title="",
            concept="ph_scale",
            scenes=[_make_scene(i) for i in range(3)],
        )


def test_storyboard_with_whitespace_only_title_raises_validation_error():
    with pytest.raises(ValidationError):
        Storyboard(
            title="   ",
            concept="ph_scale",
            scenes=[_make_scene(i) for i in range(3)],
        )


def test_storyboard_with_fewer_than_3_scenes_raises_validation_error():
    with pytest.raises(ValidationError):
        Storyboard(
            title="Too Few Scenes",
            concept="ph_scale",
            scenes=[_make_scene(i) for i in range(2)],
        )


def test_storyboard_with_more_than_6_scenes_raises_validation_error():
    with pytest.raises(ValidationError):
        Storyboard(
            title="Too Many Scenes",
            concept="ph_scale",
            scenes=[_make_scene(i) for i in range(7)],
        )


# --- Fallback path: primary template raises -------------------------------------


def test_generate_storyboard_falls_back_when_primary_template_raises(monkeypatch):
    def _broken_template():
        raise RuntimeError("primary template exploded")

    monkeypatch.setitem(
        storyboard_generator._PRIMARY_TEMPLATES, "ph_scale", _broken_template
    )

    result = generate_storyboard("ph_scale")
    fallback = storyboard_generator._safe_fallback_storyboard("ph_scale")

    assert result.title == fallback.title
    assert len(result.scenes) == len(fallback.scenes)
    assert result.concept == "ph_scale"


# --- Both primary and fallback raise --------------------------------------------


def test_generate_storyboard_raises_when_both_primary_and_fallback_fail(monkeypatch):
    def _broken_template():
        raise RuntimeError("primary template exploded")

    def _broken_fallback(concept):
        raise RuntimeError("fallback exploded too")

    monkeypatch.setitem(
        storyboard_generator._PRIMARY_TEMPLATES, "ph_scale", _broken_template
    )
    monkeypatch.setattr(
        storyboard_generator, "_safe_fallback_storyboard", _broken_fallback
    )

    with pytest.raises(StoryboardGenerationError):
        generate_storyboard("ph_scale")


# --- save_storyboard writes valid JSON to the correct path ---------------------


def test_save_storyboard_writes_valid_json_to_artifact_path():
    job_id = str(uuid.uuid4())
    artifact_store.create_job_directory(job_id)

    storyboard = generate_storyboard("covalent_bonds")
    written_path = save_storyboard(job_id, storyboard)

    expected_path = artifact_store.storyboard_path(job_id)
    assert written_path == expected_path
    assert expected_path.is_file()

    with open(expected_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["concept"] == "covalent_bonds"
    assert data["title"] == storyboard.title
    assert len(data["scenes"]) == len(storyboard.scenes)
