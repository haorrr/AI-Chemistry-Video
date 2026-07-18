"""Phase 2 tests: job model, in-memory job store, topic registry, core endpoints.

Job store is a module-level in-memory dict shared across the whole test session,
so every test resets it via the `reset_job_store` autouse fixture for isolation.
Any artifacts/{job_id}/ directories created during a test are removed by the
`cleanup_artifacts` autouse fixture so the repo's artifacts/ dir stays clean.
"""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import ARTIFACTS_DIR
from app.main import app
from app.services import job_service, topic_registry

LOCATION_RE = re.compile(r"^/video-requests/([0-9a-fA-F-]{36})$")


@pytest.fixture(autouse=True)
def reset_job_store():
    job_service._jobs.clear()
    yield
    job_service._jobs.clear()


@pytest.fixture(autouse=True)
def cleanup_artifacts():
    yield
    for entry in ARTIFACTS_DIR.iterdir():
        if entry.name == ".gitkeep":
            continue
        if entry.is_dir():
            import shutil

            shutil.rmtree(entry)
        else:
            entry.unlink()


# --- POST /video-requests: supported queries --------------------------------


@pytest.mark.parametrize("query", list(topic_registry.SUPPORTED_QUERIES.keys()))
def test_post_video_request_supported_query_returns_202_queued(query):
    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": query})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["query"] == query
    assert body["concept"] == topic_registry.SUPPORTED_QUERIES[query]

    location = response.headers["location"]
    match = LOCATION_RE.match(location)
    assert match is not None
    assert match.group(1) == body["job_id"]


# --- POST /video-requests: unsupported query ---------------------------------


def test_post_video_request_unsupported_query_returns_400_listing_supported():
    with TestClient(app) as client:
        response = client.post(
            "/video-requests", json={"query": "What is the boiling point of water?"}
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    for supported in topic_registry.supported_queries():
        assert supported in detail


# --- POST /video-requests: normalization (whitespace + case) -----------------


def test_post_video_request_whitespace_and_case_resolves_canonical_query():
    with TestClient(app) as client:
        response = client.post(
            "/video-requests", json={"query": "  how does the ph scale work?  "}
        )

    assert response.status_code == 202
    body = response.json()
    assert body["query"] == "How does the pH scale work?"
    assert body["concept"] == "ph_scale"


# --- POST /video-requests: length cap -----------------------------------------


def test_post_video_request_too_long_query_returns_400_not_500():
    with TestClient(app) as client:
        response = client.post("/video-requests", json={"query": "a" * 201})

    assert response.status_code == 400


# --- GET /video-requests: list -------------------------------------------------


def test_get_video_requests_lists_created_jobs_with_artifact_url():
    query = "Why do atoms form covalent bonds?"
    with TestClient(app) as client:
        create_response = client.post("/video-requests", json={"query": query})
        job_id = create_response.json()["job_id"]

        list_response = client.get("/video-requests")

    assert list_response.status_code == 200
    jobs = list_response.json()
    matching = [job for job in jobs if job["job_id"] == job_id]
    assert len(matching) == 1
    assert matching[0]["artifact_url"] == f"/video-requests/{job_id}/artifact"
    assert matching[0]["query"] == query
    assert matching[0]["concept"] == "covalent_bonds"


# --- GET /video-requests/{job_id}: detail --------------------------------------


def test_get_video_request_detail_404_for_unknown_job_id():
    unknown_id = str(uuid.uuid4())
    with TestClient(app) as client:
        response = client.get(f"/video-requests/{unknown_id}")

    assert response.status_code == 404


def test_get_video_request_detail_returns_full_detail_for_known_job():
    query = "What is the difference between ionic and covalent bonding?"
    with TestClient(app) as client:
        create_response = client.post("/video-requests", json={"query": query})
        job_id = create_response.json()["job_id"]

        detail_response = client.get(f"/video-requests/{job_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["job_id"] == job_id
    assert detail["query"] == query
    assert detail["concept"] == "ionic_vs_covalent"
    assert detail["status"] == "queued"
    assert detail["steps"] == ["job_created"]
    assert detail["error"] is None
    assert detail["artifact_url"] == f"/video-requests/{job_id}/artifact"


# --- artifacts/{job_id}/ directory created on job creation ---------------------


def test_artifact_directory_exists_immediately_after_job_creation():
    with TestClient(app) as client:
        response = client.post(
            "/video-requests", json={"query": "How does the pH scale work?"}
        )
        job_id = response.json()["job_id"]

    directory = ARTIFACTS_DIR / job_id
    assert directory.is_dir()


# --- topic_registry.resolve_concept unit tests (no HTTP) -----------------------


def test_resolve_concept_exact_match():
    result = topic_registry.resolve_concept("How does the pH scale work?")
    assert result == ("How does the pH scale work?", "ph_scale")


def test_resolve_concept_case_insensitive_match():
    result = topic_registry.resolve_concept("why do atoms form covalent bonds?")
    assert result == ("Why do atoms form covalent bonds?", "covalent_bonds")


def test_resolve_concept_whitespace_trimmed_match():
    result = topic_registry.resolve_concept(
        "   What is the difference between ionic and covalent bonding?   "
    )
    assert result == (
        "What is the difference between ionic and covalent bonding?",
        "ionic_vs_covalent",
    )


def test_resolve_concept_empty_string_returns_none():
    assert topic_registry.resolve_concept("") is None
    assert topic_registry.resolve_concept("   ") is None


def test_resolve_concept_none_returns_none():
    assert topic_registry.resolve_concept(None) is None


def test_resolve_concept_too_long_returns_none():
    too_long = "How does the pH scale work?" + "x" * 200
    assert topic_registry.resolve_concept(too_long) is None


def test_resolve_concept_non_matching_string_returns_none():
    assert topic_registry.resolve_concept("What is the atomic number of helium?") is None
