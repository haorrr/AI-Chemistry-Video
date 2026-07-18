"""Phase 6 tests: async pipeline wiring (POST triggers a real background
asyncio.create_task running pipeline_service.run_job) and the
GET /video-requests/{job_id}/artifact endpoint.

Job store is a module-level in-memory dict shared across the whole test
session, so every test resets it via the `reset_job_store` autouse fixture.

Deliberate deviation from test_phase1-4.py (matches test_phase5.py): this
file does NOT clean up artifacts/{job_id}/ directories after each test. The
real end-to-end test in particular is meant to leave its generated video on
disk for manual inspection.

Most tests stub `app.api.video_requests.pipeline_service.run_job` (or a
downstream call inside pipeline_service itself) via monkeypatch to avoid
paying the real ~8-10s edge-tts + MoviePy cost, and to avoid the lifespan
shutdown drain (`await asyncio.gather(*app.state.background_tasks, ...)` in
app/main.py) hanging every `with TestClient(app) as client:` block on a real
render. Only test_end_to_end_real_pipeline_completes_and_artifact_downloads
lets the real pipeline run.
"""

import gc
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.models import JobStatus, NarrationResult
from app.main import app
from app.services import artifact_store, job_service, topic_registry
from app.services.video_renderer import VideoValidationError

PH_QUERY = "How does the pH scale work?"
COVALENT_QUERY = "Why do atoms form covalent bonds?"
IONIC_QUERY = "What is the difference between ionic and covalent bonding?"

EXPECTED_STEPS = [
    "job_created",
    "storyboard_generated",
    "storyboard_validated",
    "audio_generated",
    "video_rendered",
    "artifact_saved",
    "job_completed",
]


@pytest.fixture(autouse=True)
def reset_job_store():
    job_service._jobs.clear()
    yield
    job_service._jobs.clear()


def _fake_narration(storyboard) -> NarrationResult:
    return NarrationResult(
        combined_path=artifact_store.audio_path("00000000-0000-0000-0000-000000000000"),
        scene_durations=[10.0] * len(storyboard.scenes),
        engine_used="stub",
    )


def _poll_until_terminal(client: TestClient, job_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    detail = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/video-requests/{job_id}").json()
        if detail["status"] in ("completed", "failed"):
            return detail
        time.sleep(0.2)
    return detail


# --- 1. Real end-to-end pipeline (slow, ~10-15s) ------------------------------


def test_end_to_end_real_pipeline_completes_and_artifact_downloads():
    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": PH_QUERY})
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        detail = _poll_until_terminal(client, job_id, timeout=60.0)
        assert detail.get("status") == "completed", detail.get("error")
        assert detail["steps"] == EXPECTED_STEPS

        artifact_response = client.get(f"/video-requests/{job_id}/artifact")

    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-type"] == "video/mp4"
    assert len(artifact_response.content) > 0


# --- 2. 404 unknown job on artifact endpoint ----------------------------------


def test_get_artifact_404_for_unknown_job():
    with TestClient(app) as client:
        response = client.get("/video-requests/00000000-0000-0000-0000-000000000000/artifact")

    assert response.status_code == 404


# --- 3. 409 "processing" case --------------------------------------------------


def test_get_artifact_409_while_processing(monkeypatch):
    import asyncio

    async def stub_run_job(job_id):
        job_service.update_job(job_id, status=JobStatus.generating_storyboard)
        await asyncio.sleep(1.0)

    monkeypatch.setattr("app.api.video_requests.pipeline_service.run_job", stub_run_job)

    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": PH_QUERY})
        job_id = response.json()["job_id"]

        time.sleep(0.1)  # let the pipeline task run its first synchronous line
        artifact_response = client.get(f"/video-requests/{job_id}/artifact")

    assert artifact_response.status_code == 409
    detail = artifact_response.json()["detail"]
    assert detail["status"] not in ("completed", "failed")


# --- 4. 409 "failed" case (real pipeline, audio_service broken) --------------


def test_get_artifact_409_failed_when_audio_service_raises(monkeypatch):
    async def broken_generate_narration(job_id, storyboard):
        raise RuntimeError("simulated audio_service failure")

    monkeypatch.setattr(
        "app.services.pipeline_service.audio_service.generate_narration",
        broken_generate_narration,
    )

    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": COVALENT_QUERY})
        job_id = response.json()["job_id"]

        detail = _poll_until_terminal(client, job_id, timeout=30.0)
        # Never leaves the job stuck in an intermediate status.
        assert detail["status"] == "failed"
        assert detail["error"] is not None
        assert "simulated audio_service failure" in detail["error"]
        # Failed before video_rendered/artifact_saved/job_completed steps.
        assert "video_rendered" not in detail["steps"]
        assert "job_completed" not in detail["steps"]

        artifact_response = client.get(f"/video-requests/{job_id}/artifact")

    assert artifact_response.status_code == 409
    body = artifact_response.json()["detail"]
    assert body["status"] == "failed"
    assert body["error"] is not None


# --- 5. Forcing a render/validation failure never produces false "completed" --


def test_pipeline_marks_failed_when_render_video_raises(monkeypatch):
    async def fake_generate_narration(job_id, storyboard):
        return _fake_narration(storyboard)

    def broken_render_video(job_id, storyboard, narration):
        raise VideoValidationError("simulated corrupt render output")

    monkeypatch.setattr(
        "app.services.pipeline_service.audio_service.generate_narration",
        fake_generate_narration,
    )
    monkeypatch.setattr(
        "app.services.pipeline_service.video_renderer.render_video", broken_render_video
    )

    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": IONIC_QUERY})
        job_id = response.json()["job_id"]

        detail = _poll_until_terminal(client, job_id, timeout=15.0)

    assert detail["status"] == "failed"
    assert "simulated corrupt render output" in detail["error"]
    assert "artifact_saved" not in detail["steps"]
    assert "job_completed" not in detail["steps"]


# --- 6. 500 completed-but-file-missing ----------------------------------------


def test_get_artifact_500_when_completed_but_file_missing(monkeypatch):
    async def stub_run_job(job_id):
        job_service.update_job(
            job_id,
            status=JobStatus.completed,
            artifact_path=artifact_store.job_directory(job_id) / "video.mp4",
            step="job_completed",
        )

    monkeypatch.setattr("app.api.video_requests.pipeline_service.run_job", stub_run_job)

    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": PH_QUERY})
        job_id = response.json()["job_id"]

        detail = _poll_until_terminal(client, job_id, timeout=5.0)
        assert detail["status"] == "completed"

        artifact_response = client.get(f"/video-requests/{job_id}/artifact")

    assert artifact_response.status_code == 500
    assert "missing" in artifact_response.json()["detail"].lower()


# --- 7. Task registry: app holds a strong reference, survives GC -------------


def test_background_task_survives_gc_due_to_app_registry(monkeypatch):
    import asyncio

    marker = {"ran": False}

    async def stub_run_job(job_id):
        await asyncio.sleep(0.3)
        marker["ran"] = True
        job_service.update_job(job_id, status=JobStatus.completed, step="job_completed")

    monkeypatch.setattr("app.api.video_requests.pipeline_service.run_job", stub_run_job)

    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": PH_QUERY})
        job_id = response.json()["job_id"]

        # No local reference to the asyncio.Task is ever held by this test
        # (the endpoint's `task` variable is already out of scope by the
        # time POST returns). Force a collection cycle to prove the app's
        # own app.state.background_tasks set — not test-side referencing —
        # is what keeps the task alive.
        gc.collect()

        detail = _poll_until_terminal(client, job_id, timeout=5.0)

    assert marker["ran"] is True
    assert detail["status"] == "completed"


# --- 8. Semaphore caps concurrent renders at 2 --------------------------------


def test_semaphore_caps_concurrent_renders_at_two(monkeypatch):
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    async def fake_generate_narration(job_id, storyboard):
        return _fake_narration(storyboard)

    def fake_render_video(job_id, storyboard, narration):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.5)
        with lock:
            state["current"] -= 1
        return artifact_store.video_path(job_id)

    monkeypatch.setattr(
        "app.services.pipeline_service.audio_service.generate_narration",
        fake_generate_narration,
    )
    monkeypatch.setattr(
        "app.services.pipeline_service.video_renderer.render_video", fake_render_video
    )

    queries = [PH_QUERY, COVALENT_QUERY, IONIC_QUERY, PH_QUERY]

    with TestClient(app) as client:
        job_ids = [
            client.post("/video-requests", json={"query": q}).json()["job_id"] for q in queries
        ]

        deadline = time.monotonic() + 20.0
        statuses = []
        while time.monotonic() < deadline:
            statuses = [
                client.get(f"/video-requests/{jid}").json()["status"] for jid in job_ids
            ]
            if all(s in ("completed", "failed") for s in statuses):
                break
            time.sleep(0.2)

    assert statuses == ["completed"] * len(job_ids)
    assert state["max"] >= 1
    assert state["max"] <= 2


# --- 9. job_service.py contains zero orchestration logic ----------------------


def test_job_service_has_zero_orchestration_logic():
    import inspect

    from app.services import job_service as job_service_module

    source = inspect.getsource(job_service_module)
    assert "def run_job" not in source
    assert "def run_pipeline" not in source
