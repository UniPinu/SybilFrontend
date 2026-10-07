"""M3: every endpoint in MVP.md section 6.5, the job queue and SSE, and the
promise that the outcome cannot be peeked at before the prediction exists.

No model inference happens here: `app.jobs.process_patient` is replaced by a
stub that emits the same stages a real run does.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.data import have_candidates
from app.store import store

pytestmark = pytest.mark.skipif(
    not have_candidates(),
    reason="data/candidates.parquet not built; run scripts/build_candidates.py",
)

RISKS = [0.0216, 0.0386, 0.0719, 0.0793, 0.0958, 0.1357]


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def fake_patient(patient_id: str, *, risks=None, cancer=False, n_slices=3) -> None:
    """Write the artifacts a finished run would leave, without running Sybil."""
    from app.data import get_candidate, outcome_payload

    risks = risks or RISKS
    candidate = get_candidate(patient_id)
    assert candidate is not None, patient_id
    directory = store.dir_for(patient_id)
    (directory / "slices").mkdir(parents=True, exist_ok=True)
    (directory / "overlay").mkdir(parents=True, exist_ok=True)
    for i in range(n_slices):
        Image.fromarray(np.full((32, 32), 40 + i, dtype=np.uint8), mode="L").save(
            directory / "slices" / f"{i:03d}.webp", format="WEBP")
        Image.fromarray(np.zeros((32, 32, 4), dtype=np.uint8), mode="RGBA").save(
            directory / "overlay" / f"{i:03d}.webp", format="WEBP")
    Image.fromarray(np.zeros((32, 48), dtype=np.uint8), mode="L").save(
        directory / "coronal.webp", format="WEBP")

    store.write_meta(patient_id, {"patient_id": patient_id, "candidate": candidate,
                                  "series": {"manufacturer": "TEST", "n_files": n_slices,
                                             "thickness_mm": 2.5}})
    store.write_result(patient_id, {
        "patient_id": patient_id,
        "risk_by_year": risks,
        "raw_mean": risks,
        "raw_per_model": [risks] * 5,
        "n_slices": n_slices,
        "width": 32,
        "height": 32,
        "slice_importance": [0.2, 0.5, 0.3][:n_slices],
        "hotspot_slice": 1,
        "coronal_size": [48, 32],
        "geometry": {"n_slices": n_slices},
        "timings": {"models": 90.0},
        "model": {"name": "sybil_ensemble", "device": "cpu"},
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    out = outcome_payload(candidate)
    out["cancer_within_6y"] = cancer
    if cancer:
        out["years_to_cancer"] = out.get("years_to_cancer") or 2
        out["diagnosis_year"] = out["years_to_cancer"] + 1
    store.write_outcome(patient_id, {**out, "available": True})
    store.touch(patient_id)


def some_ids(n=3):
    from app.data import candidates

    return candidates()["patient_id"].head(n).tolist()


# ---------------------------------------------------------------------------
def test_health_reports_the_facts(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["device"] == settings.device
    assert body["candidates"]["available"] is True
    assert body["candidates"]["exams"] > 10_000
    assert "cache_mb" in body["cache"]


def test_random_curated_needs_a_prepared_pool(client, clean_cache):
    assert client.get("/api/patients/random?mode=curated").status_code == 503


def test_random_curated_picks_from_the_pool(client, clean_cache):
    pid, other = some_ids(2)
    fake_patient(pid)
    store.write_pool_sets([pid], [])
    card = client.get("/api/patients/random?mode=curated").json()
    assert card["patient_id"] == pid
    assert card["ready"] is True
    assert card["set"] == "pool"
    assert "cancer" not in json.dumps(card).lower()  # the card never leaks it


def test_random_live_avoids_already_prepared_people(client, clean_cache):
    pid = some_ids(1)[0]
    fake_patient(pid)
    seen = {client.get("/api/patients/random?mode=live").json()["patient_id"]
            for _ in range(10)}
    assert pid not in seen


def test_person_card_has_no_outcome_fields(client, clean_cache):
    pid = some_ids(1)[0]
    card = client.get(f"/api/patients/{pid}").json()
    for forbidden in ("cancer_within_6y", "years_to_cancer", "years_followed", "stage"):
        assert forbidden not in card


def test_offline_demo_person_needs_no_candidate_list(client, clean_cache):
    """MVP.md 5.7: upstream's example scan is the offline fallback person."""
    card = client.get("/api/patients/demo_offline").json()
    assert card["display_id"] == "The example scan"
    assert "Sybil code" in card["round_label"]
    assert card["ready"] is False
    assert client.get("/api/patients/demo_offline/outcome").status_code == 404


def test_offline_demo_person_has_nothing_to_reveal(client, clean_cache):
    store.write_result("demo_offline", {"patient_id": "demo_offline", "risk_by_year": RISKS})
    store.write_outcome("demo_offline", {
        "patient_id": "demo_offline",
        "available": False,
        "note": "Upstream's demo scan has no outcome attached.",
    })
    outcome = client.get("/api/patients/demo_offline/outcome").json()
    assert outcome["available"] is False
    assert outcome["headline"] == "No outcome to reveal"
    assert outcome["cancer_within_6y"] is None


def test_unknown_patient_is_404(client):
    assert client.get("/api/patients/does_not_exist").status_code == 404


def test_outcome_is_not_served_before_the_run(client, clean_cache):
    pid = some_ids(1)[0]
    assert client.get(f"/api/patients/{pid}/outcome").status_code == 404
    assert client.get(f"/api/patients/{pid}/result").status_code == 404


def test_result_and_outcome_after_a_run(client, clean_cache):
    pid = some_ids(1)[0]
    fake_patient(pid, cancer=True)
    store.write_pool_sets([pid], [pid])

    result = client.get(f"/api/patients/{pid}/result").json()
    assert result["risk_by_year"] == RISKS
    assert result["headline_pct"] == pytest.approx(13.6, abs=0.1)
    assert result["people_in_100"] == 14
    assert result["hotspot_slice"] == 1
    assert result["reference"]["n"] == 1          # the fake patient is the reference
    assert result["band"]["band"] in {
        "Lower than typical", "Typical", "Higher than typical", "Much higher than typical"}

    outcome = client.get(f"/api/patients/{pid}/outcome").json()
    assert outcome["cancer_within_6y"] is True
    assert "diagnosed with lung cancer" in outcome["headline"]
    assert "not a diagnosis" in outcome["reminder"]


def test_no_cancer_reveal_mentions_the_follow_up(client, clean_cache):
    pid = some_ids(1)[0]
    fake_patient(pid, cancer=False)
    outcome = client.get(f"/api/patients/{pid}/outcome").json()
    assert "no lung-cancer diagnosis" in outcome["headline"]
    assert "follow-up" in outcome["headline"] or "follow-up" in outcome["reminder"]


def test_images_are_served_and_cacheable(client, clean_cache):
    pid = some_ids(1)[0]
    fake_patient(pid)
    for url in (f"/api/patients/{pid}/slices/000.webp",
                f"/api/patients/{pid}/overlay/000.webp",
                f"/api/patients/{pid}/coronal.webp"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["content-type"] == "image/webp"
        assert "immutable" in response.headers["cache-control"]
    assert client.get(f"/api/patients/{pid}/slices/999.webp").status_code == 404


def test_cohort_lists_prepared_people_with_the_caveat(client, clean_cache):
    a, b = some_ids(2)
    fake_patient(a, risks=[0.01] * 6, cancer=False)
    fake_patient(b, risks=[0.3] * 6, cancer=True)
    store.write_pool_sets([a, b], [])
    body = client.get("/api/cohort").json()
    assert [p["patient_id"] for p in body["people"]] == [a, b]  # sorted by risk
    assert body["people"][1]["cancer_within_6y"] is True
    assert "learned from" in body["caveat"]
    assert len(body["published"]) == 3
    assert body["published"][0]["auc_1y"] == 0.92


def test_cached_patient_skips_straight_to_ready(client, clean_cache):
    pid = some_ids(1)[0]
    fake_patient(pid)
    body = client.post(f"/api/patients/{pid}/run").json()
    assert body["ready"] is True and body["job_id"] is None


# --- the job queue and SSE --------------------------------------------------
@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace the real pipeline with one that emits the same stages."""
    from app import jobs as jobs_module

    calls: list[str] = []

    def fake_process(patient_id, emit=None, **kwargs):
        calls.append(patient_id)
        emit = emit or (lambda *a, **k: None)
        emit("downloading", bytes_done=0, bytes_total=83_000_000)
        emit("downloading", bytes_done=83_000_000, bytes_total=83_000_000)
        emit("reading", n_slices=154)
        emit("standardizing")
        for i in range(5):
            emit("model", index=i + 1, of=5)
        emit("calibrating")
        emit("rendering")
        fake_patient(patient_id)
        emit("done", patient_id=patient_id, cached=False)

    monkeypatch.setattr(jobs_module, "process_patient", fake_process)
    monkeypatch.setattr("app.main.weights_present", lambda: True)
    return calls


def read_events(client, job_id, limit=40):
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        name = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((name, json.loads(line.split(":", 1)[1].strip())))
                if name in {"done", "error"} or len(events) >= limit:
                    break
    return events


def test_run_streams_every_stage(client, clean_cache, stub_pipeline):
    pid = some_ids(1)[0]
    started = client.post(f"/api/patients/{pid}/run").json()
    assert started["job_id"]

    events = read_events(client, started["job_id"])
    names = [n for n, _ in events]
    for stage in ("queued", "downloading", "reading", "standardizing",
                  "model", "calibrating", "rendering", "done"):
        assert stage in names, f"missing {stage} in {names}"
    assert names[-1] == "done"
    assert names.count("model") == 5
    assert [d["index"] for n, d in events if n == "model"] == [1, 2, 3, 4, 5]
    download = [d for n, d in events if n == "downloading"][-1]
    assert download["bytes_done"] == download["bytes_total"] == 83_000_000
    assert all("text" in d for _, d in events if _ != "ping")
    assert store.is_ready(pid)


def test_second_request_queues_behind_the_first(client, clean_cache, stub_pipeline):
    a, b = some_ids(2)
    first = client.post(f"/api/patients/{a}/run").json()
    second = client.post(f"/api/patients/{b}/run").json()
    assert first["job_id"] != second["job_id"]

    for job_id in (first["job_id"], second["job_id"]):
        names = [n for n, _ in read_events(client, job_id)]
        assert names[0] == "queued"
        assert names[-1] == "done"
    # a single worker, so the two ran one after the other
    assert stub_pipeline == [a, b]


def test_same_patient_twice_reuses_the_job(client, clean_cache, stub_pipeline, monkeypatch):
    from app import jobs as jobs_module

    release = {"go": False}

    def slow_process(patient_id, emit=None, **kwargs):
        emit("reading", n_slices=1)
        while not release["go"]:
            time.sleep(0.01)
        emit("done", patient_id=patient_id)

    monkeypatch.setattr(jobs_module, "process_patient", slow_process)
    pid = some_ids(1)[0]
    try:
        first = client.post(f"/api/patients/{pid}/run").json()
        second = client.post(f"/api/patients/{pid}/run").json()
        assert first["job_id"] == second["job_id"]
    finally:
        release["go"] = True


def test_job_errors_reach_the_client_in_plain_language(client, clean_cache, monkeypatch):
    from app import jobs as jobs_module
    from app.pipeline import PipelineError

    def boom(patient_id, emit=None, **kwargs):
        raise PipelineError("s5cmd exited 1", stage="downloading")

    monkeypatch.setattr(jobs_module, "process_patient", boom)
    monkeypatch.setattr("app.main.weights_present", lambda: True)
    pid = some_ids(1)[0]
    job_id = client.post(f"/api/patients/{pid}/run").json()["job_id"]

    events = read_events(client, job_id)
    name, payload = events[-1]
    assert name == "error"
    assert payload["stage"] == "downloading"
    assert "Imaging Data Commons" in payload["message"]
    assert "s5cmd" not in payload["message"]  # no raw tracebacks in the UI
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "error"


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/deadbeef/events").status_code == 404
    assert client.get("/api/jobs/deadbeef").status_code == 404


# --- cache eviction ---------------------------------------------------------
def test_eviction_drops_unpinned_patients_first(clean_cache):
    a, b, c = some_ids(3)
    for pid in (a, b, c):
        fake_patient(pid, n_slices=3)
    store.write_pool_sets([a], [])          # a is pinned, b and c are not
    store.touch(b)
    time.sleep(0.01)
    store.touch(c)

    evicted = store.evict(max_mb=store.size_mb() - 0.001)
    assert evicted and a not in evicted
    assert store.is_ready(a)
    assert evicted[0] == b                  # least recently used goes first
