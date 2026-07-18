"""End-to-end demo/verification script for the AI Chemistry Video Request Service.

Exercises the full pipeline for all 3 required chemistry concepts against the
FastAPI app in-process, copies the completed videos to sample_outputs/, and
prints a pass/fail summary covering master prompt §15's minimum verification
list: create x3, list, detail, artifact-exists, unsupported-query-400.

Uses TestClient as a context manager (`with TestClient(app) as client:`) so the
app's lifespan actually starts — this is required for the background pipeline
tasks (asyncio.create_task) to run reliably; using TestClient(app) without the
`with` block would make status polling meaningless.

Usage:
    python run_demo.py
"""

import sys
import time

from fastapi.testclient import TestClient

from app.config import SAMPLE_OUTPUTS_DIR
from app.main import app
from app.services import video_renderer

POLL_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 1.0

REQUIRED_QUERIES = {
    "ph_scale": "How does the pH scale work?",
    "covalent_bonds": "Why do atoms form covalent bonds?",
    "ionic_vs_covalent": "What is the difference between ionic and covalent bonding?",
}


def _check(condition: bool, message: str, results: list) -> bool:
    status = "PASS" if condition else "FAIL"
    results.append((status, message))
    print(f"[{status}] {message}")
    return condition


def _poll_until_terminal(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    detail = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/video-requests/{job_id}").json()
        if detail.get("status") in ("completed", "failed"):
            return detail
        time.sleep(POLL_INTERVAL_SECONDS)
    detail["status"] = detail.get("status", "timeout")
    return detail


def main() -> int:
    results: list[tuple[str, str]] = []
    SAMPLE_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        r = client.get("/health")
        _check(r.status_code == 200 and r.json() == {"status": "ok"}, "GET /health returns ok", results)

        r = client.post("/video-requests", json={"query": "What is the boiling point of water?"})
        _check(r.status_code == 400, "POST unsupported query returns 400", results)

        r = client.post("/video-requests", json={"query": "  how does the ph scale work?  "})
        _check(
            r.status_code == 202 and r.json().get("concept") == "ph_scale",
            "POST whitespace/wrong-case query normalizes and returns 202",
            results,
        )

        job_ids: dict[str, str] = {}
        for concept, query in REQUIRED_QUERIES.items():
            r = client.post("/video-requests", json={"query": query})
            if _check(r.status_code == 202, f"POST create job for {concept} returns 202", results):
                job_ids[concept] = r.json()["job_id"]

        r = client.get("/video-requests")
        listed_ok = _check(r.status_code == 200, "GET /video-requests returns 200", results)
        if listed_ok:
            listed_ids = {job["job_id"] for job in r.json()}
            _check(
                all(jid in listed_ids for jid in job_ids.values()),
                "GET /video-requests lists all created jobs",
                results,
            )

        for concept, job_id in job_ids.items():
            r = client.get(f"/video-requests/{job_id}")
            _check(
                r.status_code == 200 and r.json().get("job_id") == job_id,
                f"GET /video-requests/{{job_id}} returns detail for {concept}",
                results,
            )

            print(f"\nWaiting for {concept} (job_id={job_id}) to complete...")
            detail = _poll_until_terminal(client, job_id)
            completed = _check(
                detail.get("status") == "completed",
                f"{concept} job reached status=completed (steps={detail.get('steps')})",
                results,
            )
            if not completed:
                print(f"  error: {detail.get('error')}")
                continue

            r = client.get(f"/video-requests/{job_id}/artifact")
            artifact_ok = _check(
                r.status_code == 200 and r.headers.get("content-type") == "video/mp4",
                f"GET artifact for {concept} returns 200 video/mp4",
                results,
            )
            if not artifact_ok:
                continue

            dest = SAMPLE_OUTPUTS_DIR / f"{concept}.mp4"
            dest.write_bytes(r.content)

            try:
                video_renderer.validate_video(dest)
                valid = True
            except video_renderer.VideoValidationError as e:
                valid = False
                print(f"  validate_video failed: {e}")
            _check(valid, f"sample_outputs/{concept}.mp4 passes validate_video()", results)

    passed = sum(1 for status, _ in results if status == "PASS")
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Demo summary: {passed}/{total} checks passed")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
